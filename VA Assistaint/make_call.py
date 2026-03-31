# Download the helper library from https://www.twilio.com/docs/python/install
import os
from twilio.rest import Client

# First, let's try to load the .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ dotenv loaded successfully")
except ImportError:
    print("✗ python-dotenv not installed. Install with: pip install python-dotenv")
    exit(1)
except Exception as e:
    print(f"✗ Error loading .env file: {e}")

# Debug: Print current working directory
print(f"Current working directory: {os.getcwd()}")
print(f".env file exists: {os.path.exists('.env')}")

# Debug: Try to load environment variables
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

print(f"TWILIO_ACCOUNT_SID loaded: {'✓' if account_sid else '✗'}")
print(f"TWILIO_AUTH_TOKEN loaded: {'✓' if auth_token else '✗'}")

# If .env isn't working, fall back to direct assignment for testing
if not account_sid or not auth_token:
    print("\n⚠️  Environment variables not found, using direct assignment...")
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

try:
    call = client.calls.create(
        url="http://demo.twilio.com/docs/voice.xml",
        to="+923498312724",
        from_="+12316266198",
    )
    print(f"✓ Call created successfully! SID: {call.sid}")
    
except Exception as e:
    print(f"✗ Error creating call: {e}")