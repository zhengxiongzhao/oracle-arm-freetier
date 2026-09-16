FROM python:3.12-alpine

# 仅安装依赖;代码/配置/密钥通过运行时挂载提供(路径与宿主一致)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# 与 oci.env 中的绝对路径保持一致
WORKDIR /workspace/oracle-freetier-instance-creation

CMD ["python", "main.py"]
