"""Read-only sanity check for OCI credentials and target subnet.

Reads settings from oci.env (same source as main.py) and verifies:
  1. API key auth works (get_user)
  2. Availability domains visible
  3. The configured OCI_SUBNET_ID exists in the tenancy
  4. Lists existing instances (to see free-tier usage)
"""
import os

import oci
from dotenv import load_dotenv

load_dotenv("oci.env")

SUBNET_ID = os.getenv("OCI_SUBNET_ID", "").strip()

config = oci.config.from_file(os.getenv("OCI_CONFIG", "oci_config").strip())

identity = oci.identity.IdentityClient(config)
network = oci.core.VirtualNetworkClient(config)
compute = oci.core.ComputeClient(config)

# 1) Validate auth + get tenancy
user_info = identity.get_user(config["user"]).data
tenancy = user_info.compartment_id
print("AUTH OK - tenancy =", tenancy)

# 2) List availability domains
ads = identity.list_availability_domains(compartment_id=tenancy).data
print("AVAILABILITY DOMAINS:")
for ad in ads:
    print("   ", ad.name)

# 3) List subnets and check the provided subnet OCID
subnets = network.list_subnets(compartment_id=tenancy).data
print("SUBNETS:")
found = False
for s in subnets:
    mark = "  <== TARGET" if s.id == SUBNET_ID else ""
    if s.id == SUBNET_ID:
        found = True
    print(f"   {s.display_name}  |  {s.id}{mark}")
print("SUBNET_MATCH:", found)

# 4) Check if any instances already exist
instances = compute.list_instances(compartment_id=tenancy).data
print("EXISTING INSTANCES:", [(i.display_name, i.shape, i.lifecycle_state) for i in instances])