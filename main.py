import configparser
import itertools
import json
import logging
import os
import smtplib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Union

import oci
import paramiko
from dotenv import load_dotenv
import requests

OCI_RETRYABLE_EXCEPTIONS = (
    oci.exceptions.RequestException,
    oci.exceptions.ClientError,
    getattr(oci.exceptions, 'ConnectTimeout', Exception),
    getattr(oci.exceptions, 'BaseConnectTimeout', Exception),
    getattr(oci.exceptions, 'BaseRequestException', Exception),
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
)

# Load environment variables from .env file
load_dotenv('oci.env')

ARM_SHAPE = "VM.Standard.A1.Flex"
E2_MICRO_SHAPE = "VM.Standard.E2.1.Micro"

# Access loaded environment variables and strip white spaces
OCI_CONFIG = os.getenv("OCI_CONFIG", "").strip()
OCT_FREE_AD = os.getenv("OCT_FREE_AD", "").strip()
DISPLAY_NAME = os.getenv("DISPLAY_NAME", "").strip()
WAIT_TIME = int(os.getenv("REQUEST_WAIT_TIME_SECS", "0").strip())
SSH_AUTHORIZED_KEYS_FILE = os.getenv("SSH_AUTHORIZED_KEYS_FILE", "").strip()
# ARM (VM.Standard.A1.Flex) 实例规格,可在 oci.env 覆盖;默认 1 OCPU / 6 GB
OCI_OCPUS = int(os.getenv("OCI_OCPUS", "1"))
OCI_MEMORY_IN_GBS = int(os.getenv("OCI_MEMORY_IN_GBS", "6"))
OCI_IMAGE_ID = os.getenv("OCI_IMAGE_ID", None).strip() if os.getenv("OCI_IMAGE_ID") else None
OCI_COMPUTE_SHAPE = os.getenv("OCI_COMPUTE_SHAPE", ARM_SHAPE).strip()
SECOND_MICRO_INSTANCE = os.getenv("SECOND_MICRO_INSTANCE", 'False').strip().lower() == 'true'
OCI_SUBNET_ID = os.getenv("OCI_SUBNET_ID", None).strip() if os.getenv("OCI_SUBNET_ID") else None
OPERATING_SYSTEM = os.getenv("OPERATING_SYSTEM", "").strip()
OS_VERSION = os.getenv("OS_VERSION", "").strip()
ASSIGN_PUBLIC_IP = os.getenv("ASSIGN_PUBLIC_IP", "false").strip()
BOOT_VOLUME_SIZE = os.getenv("BOOT_VOLUME_SIZE", "50").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", 'False').strip().lower() == 'true'
EMAIL = os.getenv("EMAIL", "").strip()
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "").strip()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID", "").strip()
WECHAT_CLAWBOT_TOKEN = os.getenv("WECHAT_CLAWBOT_TOKEN", "").strip()
WECHAT_CLAWBOT_BASEURL = os.getenv("WECHAT_CLAWBOT_BASEURL", "").strip()
WECHAT_TO_USER_ID = os.getenv("WECHAT_TO_USER_ID", "").strip()
WECHAT_CTX_TOKEN = os.getenv("WECHAT_CTX_TOKEN", "").strip()
# ClawBot 网关服务（本地加密接口）。配置后微信通知优先走网关
# （网关承担 ClawBot 登录状态/保活管理），格式 http://容器名:端口
WECHAT_GATEWAY_URL = os.getenv("WECHAT_GATEWAY_URL", "").strip()
WECHAT_GATEWAY_API_KEY = os.getenv("WECHAT_GATEWAY_API_KEY", "").strip()

# Read the configuration from oci_config file
config = configparser.ConfigParser()
try:
    config.read(OCI_CONFIG)
    OCI_USER_ID = config.get('DEFAULT', 'user')
    if OCI_COMPUTE_SHAPE not in (ARM_SHAPE, E2_MICRO_SHAPE):
        raise ValueError(f"{OCI_COMPUTE_SHAPE} is not an acceptable shape")
    env_has_spaces = any(isinstance(confg_var, str) and " " in confg_var
                        for confg_var in [OCI_CONFIG, OCT_FREE_AD,WAIT_TIME,
                                SSH_AUTHORIZED_KEYS_FILE, OCI_IMAGE_ID, 
                                OCI_COMPUTE_SHAPE, SECOND_MICRO_INSTANCE, 
                                OCI_SUBNET_ID, OS_VERSION, NOTIFY_EMAIL,EMAIL,
                                EMAIL_PASSWORD, DISCORD_WEBHOOK,
                                TELEGRAM_TOKEN, TELEGRAM_USER_ID,
                                WECHAT_CLAWBOT_TOKEN, WECHAT_CLAWBOT_BASEURL,
                                WECHAT_TO_USER_ID, WECHAT_CTX_TOKEN]
                        )
    config_has_spaces = any(' ' in value for section in config.sections() 
                            for _, value in config.items(section))
    if env_has_spaces:
        raise ValueError("oci.env has spaces in values which is not acceptable")
    if config_has_spaces:
        raise ValueError("oci_config has spaces in values which is not acceptable")        

except configparser.NoSectionError:
    msg = (
        "oci_config is missing the [DEFAULT] section. "
        "Ensure your config file matches the format shown in sample_oci_config."
    )
    with open("ERROR_IN_CONFIG.log", "w", encoding='utf-8') as file:
        file.write(msg)
    print(msg)

except configparser.NoOptionError:
    msg = (
        "oci_config is missing the 'user' key under [DEFAULT]. "
        "Copy the OCID from your OCI profile and add: user=ocid1.user.oc1..<your-ocid>. "
        "Refer to sample_oci_config for the expected format."
    )
    with open("ERROR_IN_CONFIG.log", "w", encoding='utf-8') as file:
        file.write(msg)
    print(msg)

except configparser.Error as e:
    with open("ERROR_IN_CONFIG.log", "w", encoding='utf-8') as file:
        file.write(str(e))

    print(f"Error reading the configuration file: {e}")

# Set up logging
# LOG_TO: 日志输出目标 — stdout(默认,容器标准输出,便于 docker logs 查看) / file(仅文件) / both(两者)
LOG_TO = os.getenv("LOG_TO", "stdout").strip().lower()
if LOG_TO not in ("stdout", "file", "both"):
    LOG_TO = "stdout"

_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

# 根 logger(setup_and_info 类消息):按 LOG_TO 装配输出 handler
_root_handlers = []
if LOG_TO in ("file", "both"):
    _root_handlers.append(logging.FileHandler("setup_and_info.log"))
if LOG_TO in ("stdout", "both"):
    _root_handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=_root_handlers,
)

# 抢实例轮询 logger(launch_instance):file/both 模式写入 launch_instance.log,
# stdout 模式不加自有 handler,经 propagate 由根 logger 输出到标准输出(避免重复行)
logging_step5 = logging.getLogger("launch_instance")
logging_step5.setLevel(logging.INFO)
if LOG_TO in ("file", "both"):
    fh = logging.FileHandler("launch_instance.log")
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging_step5.addHandler(fh)

# Set up OCI Config and Clients
oci_config_path = OCI_CONFIG if OCI_CONFIG else "~/.oci/config"
config = oci.config.from_file(oci_config_path)
iam_client = oci.identity.IdentityClient(config)
network_client = oci.core.VirtualNetworkClient(config)
compute_client = oci.core.ComputeClient(config)

IMAGE_LIST_KEYS = [
    "lifecycle_state",
    "display_name",
    "id",
    "operating_system",
    "operating_system_version",
    "size_in_mbs",
    "time_created",
]


def write_into_file(file_path, data):
    """Write data into a file.

    Args:
        file_path (str): The path of the file.
        data (str): The data to be written into the file.
    """
    with open(file_path, mode="a", encoding="utf-8") as file_writer:
        file_writer.write(data)


def send_email(subject, body, email, password):
    """Send an HTML email using the SMTP protocol.

    Args:
        subject (str): The subject of the email.
        body (str): The HTML body/content of the email.
        email (str): The sender's email address.
        password (str): The sender's email password or app-specific password.

    Raises:
        smtplib.SMTPException: If an error occurs during the SMTP communication.
    """
    # Set up the MIME
    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = email
    message["To"] = email

    # Attach HTML content to the email
    html_body = MIMEText(body, "html")
    message.attach(html_body)

    # Connect to the SMTP server
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        try:
            # Start TLS for security
            server.starttls()
            # Login to the server
            server.login(email, password)
            # Send the email
            server.sendmail(email, email, message.as_string())
        except smtplib.SMTPException as mail_err:
            # Handle SMTP exceptions (e.g., authentication failure, connection issues)
            logging.error("Error while sending email: %s", mail_err)
            raise


def list_all_instances(compartment_id):
    """Retrieve a list of all instances in the specified compartment.

    Args:
        compartment_id (str): The compartment ID.

    Returns:
        list: The list of instances returned from the OCI service.
    """
    return execute_oci_command(
        compute_client,
        "list_instances",
        compartment_id=compartment_id,
    )


def generate_html_body(instance):
    """Generate HTML body for the email with instance details.

    Args:
        instance (dict): The instance dictionary returned from the OCI service.

    Returns:
        str: HTML body for the email.
    """
    # Replace placeholders with instance details
    with open('email_content.html', 'r', encoding='utf-8') as email_temp:
        html_template = email_temp.read()
    html_body = html_template.replace('&lt;INSTANCE_ID&gt;', instance.id)
    html_body = html_body.replace('&lt;DISPLAY_NAME&gt;', instance.display_name)
    html_body = html_body.replace('&lt;AD&gt;', instance.availability_domain)
    html_body = html_body.replace('&lt;SHAPE&gt;', instance.shape)
    html_body = html_body.replace('&lt;STATE&gt;', instance.lifecycle_state)

    return html_body


def create_instance_details_file_and_notify(instance, shape=ARM_SHAPE):
    """Create a file with details of instances and notify the user.

    Args:
        instance (dict): The instance dictionary returned from the OCI service.
        shape (str): shape of the instance to be created, acceptable values are
         "VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"
    """
    details = [f"Instance ID: {instance.id}",
               f"Display Name: {instance.display_name}",
               f"Availability Domain: {instance.availability_domain}",
               f"Shape: {instance.shape}",
               f"State: {instance.lifecycle_state}",
               "\n"]
    micro_body = 'TWo Micro Instances are already existing and running'
    arm_body = '\n'.join(details)
    body = arm_body if shape == ARM_SHAPE else micro_body
    write_into_file('INSTANCE_CREATED', body)

    # Generate HTML body for email
    html_body = generate_html_body(instance)

    # 并发通知所有已配置渠道（Gmail / Telegram / WeChat / Discord）
    notify_all(
        "🎉 OCI 实例创建成功！\n\n" + body.strip(),
        email_subject='OCI INSTANCE CREATED',
        email_html=html_body,
    )


def notify_on_failure(failure_msg):
    """Notifies users when the Instance Creation Failed due to an error that's
    not handled.

    Args:
        failure_msg (msg): The error message.
    """

    mail_body = (
        "The script encountered an unhandled error and exited unexpectedly.\n\n"
        "Please re-run the script by executing './setup_init.sh rerun'.\n\n"
        "And raise a issue on GitHub if its not already existing:\n"
        "https://github.com/mohankumarpaluru/oracle-freetier-instance-creation/issues\n\n"
        " And include the following error message to help us investigate and resolve the problem:\n\n"
        f"{failure_msg}"
    )
    write_into_file('UNHANDLED_ERROR.log', mail_body)
    # 并发通知所有已配置渠道（Gmail / Telegram / WeChat / Discord）
    notify_all(
        "😱 OCI 抢实例脚本遇到未处理错误：\n" + failure_msg,
        email_subject='OCI INSTANCE CREATION SCRIPT: FAILED DUE TO AN ERROR',
        email_html=f"<pre>{mail_body}</pre>",
    )


def check_instance_state_and_write(compartment_id, shape, states=('RUNNING', 'PROVISIONING'),
                                   tries=3):
    """Check the state of instances in the specified compartment and take action when a matching instance is found.

    Args:
        compartment_id (str): The compartment ID to check for instances.
        shape (str): The shape of the instance.
        states (tuple, optional): The lifecycle states to consider. Defaults to ('RUNNING', 'PROVISIONING').
        tries(int, optional): No of reties until an instance is found. Defaults to 3.

    Returns:
        bool: True if a matching instance is found, False otherwise.
    """
    for _ in range(tries):
        instance_list = list_all_instances(compartment_id=compartment_id)
        if shape == ARM_SHAPE:
            running_arm_instance = next((instance for instance in instance_list if
                                         instance.shape == shape and instance.lifecycle_state in states), None)
            if running_arm_instance:
                create_instance_details_file_and_notify(running_arm_instance, shape)
                return True
        else:
            micro_instance_list = [instance for instance in instance_list if
                                   instance.shape == shape and instance.lifecycle_state in states]
            if len(micro_instance_list) > 1 and SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                return True
            if len(micro_instance_list) == 1 and not SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                return True       
        if tries - 1 > 0:
            time.sleep(60)

    return False


def handle_errors(command, data, log):
    """Handles errors and logs messages.

    Args:
        command (arg): The OCI command being executed.
        data (dict): The data or error information returned from the OCI service.
        log (logging.Logger): The logger instance for logging messages.

    Returns:
        bool: True if the error is temporary and the operation should be retried after a delay.
        Raises Exception for unexpected errors.
    """

    # Check for temporary errors that can be retried
    retryable_codes = {
        "TooManyRequests",
        "Out of host capacity.",
        "InternalError",
        "RequestException",
        "CannotParseRequest",
        "LimitExceeded",
        "ServiceUnavailable",
        "Conflict",
    }
    retryable_statuses = {429, 500, 502, 503, 504}
    retryable_messages = (
        "Out of host capacity.",
        "Bad Gateway",
        "Max retries exceeded",
        "ProxyError",
        "Tunnel connection failed",
        "Connection aborted",
        "ConnectTimeout",
        "Read timed out",
        "CannotParseRequest",
        "Incorrectly formatted request",
    )
    message = data.get("message", "")

    if (
        data.get("code") in retryable_codes
        or data.get("status") in retryable_statuses
        or any(retry_msg in message for retry_msg in retryable_messages)
    ):
        log.info("Command: %s--\nOutput: %s", command, data)
        time.sleep(WAIT_TIME)
        return True

    failure_msg = '\n'.join([f'{key}: {value}' for key, value in data.items()])
    notify_on_failure(failure_msg)
    # Raise an exception for unexpected errors
    raise Exception("Error: %s" % data)


def execute_oci_command(client, method, *args, **kwargs):
    """Executes an OCI command using the specified OCI client.

    Args:
        client: The OCI client instance.
        method (str): The method to call on the OCI client.
        args: Additional positional arguments to pass to the OCI client method.
        kwargs: Additional keyword arguments to pass to the OCI client method.

    Returns:
        dict: The data returned from the OCI service.

    Raises:
        Exception: Raises an exception if an unexpected error occurs.
    """
    while True:
        try:
            response = getattr(client, method)(*args, **kwargs)
            data = response.data if hasattr(response, "data") else response
            return data
        except oci.exceptions.ServiceError as srv_err:
            data = {"status": srv_err.status,
                    "code": srv_err.code,
                    "message": srv_err.message}
            handle_errors(args, data, logging_step5)
        except OCI_RETRYABLE_EXCEPTIONS as req_err:
            data = {
                "status": None,
                "code": "RequestException",
                "message": str(req_err),
            }
            handle_errors(args, data, logging_step5)


def generate_ssh_key_pair(public_key_file: Union[str, Path], private_key_file: Union[str, Path]):
    """Generates an SSH key pair and saves them to the specified files.

    Args:
        public_key_file :file to save the public key.
        private_key_file : The file to save the private key.
    """
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(private_key_file)
    # Save public key to file
    write_into_file(public_key_file, (f"ssh-rsa {key.get_base64()} "
                                      f"{Path(public_key_file).stem}_auto_generated"))


def read_or_generate_ssh_public_key(public_key_file: Union[str, Path]):
    """Reads the SSH public key from the file if it exists, else generates and reads it.

    Args:
        public_key_file: The file containing the public key.

    Returns:
        Union[str, Path]: The SSH public key.
    """
    public_key_path = Path(public_key_file)

    if not public_key_path.is_file():
        logging.info("SSH key doesn't exist... Generating SSH Key Pair")
        public_key_path.parent.mkdir(parents=True, exist_ok=True)
        private_key_path = public_key_path.with_name(f"{public_key_path.stem}_private")
        generate_ssh_key_pair(public_key_path, private_key_path)

    with open(public_key_path, "r", encoding="utf-8") as pub_key_file:
        ssh_public_key = pub_key_file.read()

    return ssh_public_key


def notify_all(message, email_subject=None, email_html=None):
    """并发通知所有已配置渠道（Gmail / Telegram / WeChat / Discord）。

    每个渠道独立判断是否已配置；配置了几个就并发发几个，
    任一渠道失败只记日志，不阻塞其他渠道。线程池上限 4。
    """
    tasks = []

    if NOTIFY_EMAIL and EMAIL and EMAIL_PASSWORD:
        def _mail():
            send_email(email_subject or 'OCI NOTIFICATION',
                       email_html or f"<p>{message}</p>", EMAIL, EMAIL_PASSWORD)
        tasks.append(_mail)

    if TELEGRAM_TOKEN and TELEGRAM_USER_ID:
        tasks.append(lambda: send_telegram_message(message))

    if WECHAT_GATEWAY_URL or (WECHAT_CLAWBOT_TOKEN and WECHAT_TO_USER_ID and WECHAT_CTX_TOKEN):
        tasks.append(lambda: send_wechat_message(message))

    if DISCORD_WEBHOOK:
        tasks.append(lambda: send_discord_message(message))

    if not tasks:
        return

    def _safe(fn):
        try:
            fn()
        except Exception as exc:
            logging.error("Notification channel error: %s", exc)

    with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
        list(pool.map(_safe, tasks))


def send_discord_message(message):
    """Send a message to Discord using the webhook URL if available."""
    if DISCORD_WEBHOOK:
        payload = {"content": message}
        try:
            response = requests.post(DISCORD_WEBHOOK, json=payload)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error("Failed to send Discord message: %s", e)


def send_telegram_message(message):
    """Send a message to Telegram via the bot if token and user id are configured."""
    if TELEGRAM_TOKEN and TELEGRAM_USER_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_USER_ID, "text": message}
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error("Failed to send Telegram message: %s", e)


def send_wechat_message(message):
    """Send a message to WeChat via Tencent iLink ClawBot API if configured.

    Prefers the local ClawBot gateway (WECHAT_GATEWAY_URL) when configured;
    falls back to direct iLink API when only the four ClawBot keys are set.
    """
    if WECHAT_GATEWAY_URL:
        try:
            import hashlib
            import hmac
            url = WECHAT_GATEWAY_URL.rstrip("/") + "/api/v1/send"
            payload = {"text": message}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            ts = int(time.time())
            if WECHAT_GATEWAY_API_KEY:
                headers["X-API-Key"] = WECHAT_GATEWAY_API_KEY
                headers["X-Timestamp"] = str(ts)
                # 签名: hmac(secret, method|path|timestamp|sha256(body))
                # 签名密钥默认取 API Key 本身, 可用 WECHAT_GATEWAY_SECRET 覆盖
                secret = os.getenv("WECHAT_GATEWAY_SECRET", "").strip() or WECHAT_GATEWAY_API_KEY
                if secret:
                    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
                    mac.update(b"POST")
                    mac.update(b"|")
                    mac.update(b"/api/v1/send")
                    mac.update(b"|")
                    mac.update(str(ts).encode())
                    mac.update(b"|")
                    mac.update(hashlib.sha256(body).hexdigest().encode())
                    headers["X-Signature"] = mac.hexdigest()
            response = requests.post(url, data=body, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logging.error("WeChat gateway send failed: %s", data)
            return
        except Exception as e:
            logging.error("Failed to send via WeChat gateway: %s", e)
            # gateway 失败时若仍有直连凭据则降级直连
            if not (WECHAT_CLAWBOT_TOKEN and WECHAT_TO_USER_ID and WECHAT_CTX_TOKEN):
                return
    if not (WECHAT_CLAWBOT_TOKEN and WECHAT_TO_USER_ID and WECHAT_CTX_TOKEN):
        return
    try:
        import base64
        import secrets
        uin = base64.b64encode(str(secrets.randbits(32)).encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": uin,
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 6),
            "Authorization": f"Bearer {WECHAT_CLAWBOT_TOKEN}",
        }
        base_url = (WECHAT_CLAWBOT_BASEURL or "https://ilinkai.weixin.qq.com").rstrip("/")
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": WECHAT_TO_USER_ID,
                "client_id": f"oci-notify:{int(time.time() * 1000)}-{secrets.token_hex(4)}",
                "message_type": 2,
                "message_state": 2,
                "context_token": WECHAT_CTX_TOKEN,
                "item_list": [{"type": 1, "text_item": {"text": message}}],
            },
            "base_info": {"channel_version": "2.4.6", "bot_agent": "oci-instance-notify/1.0 (python)"},
        }
        response = requests.post(f"{base_url}/ilink/bot/sendmessage", json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("ret") not in (0, None, "") or data.get("errcode") not in (0, None, ""):
            logging.error("WeChat send failed: %s", data)
    except Exception as e:
        logging.error("Failed to send WeChat message: %s", e)


def launch_instance():
    """Launches an OCI Compute instance using the specified parameters.

    Raises:
        Exception: Raises an exception if an unexpected error occurs.
    """
    # Step 1 - Get TENANCY
    user_info = execute_oci_command(iam_client, "get_user", OCI_USER_ID)
    oci_tenancy = user_info.compartment_id
    logging.info("OCI_TENANCY: %s", oci_tenancy)

    # Step 2 - Get AD Name
    availability_domains = execute_oci_command(iam_client,
                                               "list_availability_domains",
                                               compartment_id=oci_tenancy)
    oci_ad_name = [item.name for item in availability_domains if
                   any(item.name.endswith(oct_ad) for oct_ad in OCT_FREE_AD.split(","))]
    oci_ad_names = itertools.cycle(oci_ad_name)
    logging.info("OCI_AD_NAME: %s", oci_ad_name)

    # Step 3 - Get Subnet ID
    oci_subnet_id = OCI_SUBNET_ID
    if not oci_subnet_id:
        subnets = execute_oci_command(network_client,
                                      "list_subnets",
                                      compartment_id=oci_tenancy)
        oci_subnet_id = subnets[0].id
    logging.info("OCI_SUBNET_ID: %s", oci_subnet_id)

    # Step 4 - Get Image ID of Compute Shape
    if not OCI_IMAGE_ID:
        images = execute_oci_command(
            compute_client,
            "list_images",
            compartment_id=oci_tenancy,
            shape=OCI_COMPUTE_SHAPE,
        )
        shortened_images = [{key: json.loads(str(image))[key] for key in IMAGE_LIST_KEYS
                             } for image in images]
        write_into_file('images_list.json', json.dumps(shortened_images, indent=2))
        oci_image_id = next(image.id for image in images if
                            image.operating_system == OPERATING_SYSTEM and
                            image.operating_system_version == OS_VERSION)
        logging.info("OCI_IMAGE_ID: %s", oci_image_id)
    else:
        oci_image_id = OCI_IMAGE_ID

    assign_public_ip = ASSIGN_PUBLIC_IP.lower() in [ "true", "1", "y", "yes" ]

    boot_volume_size = max(50, int(BOOT_VOLUME_SIZE))

    ssh_public_key = read_or_generate_ssh_public_key(SSH_AUTHORIZED_KEYS_FILE)

    # Step 5 - Launch Instance if it's not already exist and running
    instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE, tries=1)

    if OCI_COMPUTE_SHAPE == "VM.Standard.A1.Flex":
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCI_OCPUS, memory_in_gbs=OCI_MEMORY_IN_GBS)
        logging.info("ARM shape config: %s OCPU / %s GB (在 OCI 控制台创建实例页面可确认规格)",
                     OCI_OCPUS, OCI_MEMORY_IN_GBS)
    else:
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1, memory_in_gbs=1)

    while not instance_exist_flag:
        try:
            launch_instance_response = compute_client.launch_instance(
                launch_instance_details=oci.core.models.LaunchInstanceDetails(
                    availability_domain=next(oci_ad_names),
                    compartment_id=oci_tenancy,
                    create_vnic_details=oci.core.models.CreateVnicDetails(
                        assign_public_ip=assign_public_ip,
                        assign_private_dns_record=True,
                        display_name=DISPLAY_NAME,
                        subnet_id=oci_subnet_id,
                    ),
                    display_name=DISPLAY_NAME,
                    shape=OCI_COMPUTE_SHAPE,
                    availability_config=oci.core.models.LaunchInstanceAvailabilityConfigDetails(
                        recovery_action="RESTORE_INSTANCE"
                    ),
                    instance_options=oci.core.models.InstanceOptions(
                        are_legacy_imds_endpoints_disabled=False
                    ),
                    shape_config=shape_config,
                    source_details=oci.core.models.InstanceSourceViaImageDetails(
                        source_type="image",
                        image_id=oci_image_id,
                        boot_volume_size_in_gbs=boot_volume_size,
                    ),
                    metadata={
                        "ssh_authorized_keys": ssh_public_key},
                )
            )
            if launch_instance_response.status == 200:
                logging_step5.info(
                    "Command: launch_instance\nOutput: %s", launch_instance_response
                )
                instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE)

        except oci.exceptions.ServiceError as srv_err:
            if srv_err.code == "LimitExceeded":                
                logging_step5.info("Encoundered LimitExceeded Error checking if instance is created" \
                                   "code :%s, message: %s, status: %s", srv_err.code, srv_err.message, srv_err.status)                
                instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE)
                if instance_exist_flag:
                    logging_step5.info("%s , exiting the program", srv_err.code)
                    sys.exit()
                logging_step5.info("Didn't find an instance , proceeding with retries")     
            data = {
                "status": srv_err.status,
                "code": srv_err.code,
                "message": srv_err.message,
            }
            handle_errors("launch_instance", data, logging_step5)
        except OCI_RETRYABLE_EXCEPTIONS as req_err:
            data = {
                "status": None,
                "code": "RequestException",
                "message": str(req_err),
            }
            handle_errors("launch_instance", data, logging_step5)


if __name__ == "__main__":
    # 启动通知（并发发送所有已配置渠道）
    notify_all(
        "🚀 OCI 抢实例脚本已启动（规格 " + OCI_COMPUTE_SHAPE + "）。抢到实例后会自动通知你。",
        email_subject='OCI INSTANCE CREATION SCRIPT: STARTED',
        email_html=f"<p>🚀 OCI 抢实例脚本已启动（规格 {OCI_COMPUTE_SHAPE}）。抢到实例后会自动通知你。</p>",
    )
    try:
        launch_instance()
        notify_all(
            "🎉 OCI 实例创建成功！",
            email_subject='OCI INSTANCE CREATED',
            email_html="<p>🎉 OCI 实例创建成功！</p>",
        )
    except Exception as e:
        error_message = f"😱 Oops! Something went wrong with the OCI Instance Creation Script:\n{str(e)}"
        notify_all(
            error_message,
            email_subject='OCI INSTANCE CREATION SCRIPT: FAILED',
            email_html=f"<pre>{error_message}</pre>",
        )
        raise
