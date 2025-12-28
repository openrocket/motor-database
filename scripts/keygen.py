from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import base64

## Helper script to generate an Ed25519 keypair for OpenRocket update signing

# 1. Generate the private key
private_key = ed25519.Ed25519PrivateKey.generate()

# 2. Extract Private Key bytes (PKCS8 format is standard and easy to handle)
priv_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

# 3. Extract Public Key bytes (SubjectPublicKeyInfo format)
public_key = private_key.public_key()
pub_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.PEM, # Helper to get the bytes, we strip headers later if needed
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

# Convert to pure Base64 strings (stripping PEM headers for easier copy-pasting)
priv_b64 = base64.b64encode(priv_bytes).decode('utf-8')

# For the public key, let's get the raw bytes then base64 encode them
# so it looks like "MCowBQYDK2VwAyEA..."
raw_pub_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
pub_b64 = base64.b64encode(raw_pub_bytes).decode('utf-8')

print("=== COPY TO GITHUB SECRETS (Private Key) ===")
print(priv_b64)
print("\n=== COPY TO OPENROCKET JAVA CODE (Public Key) ===")
print(pub_b64)