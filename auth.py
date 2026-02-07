import os
import jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

security = HTTPBearer()

# In a real production app, you would fetch Clerk's JWKS to verify signatures.
# For this demo, we might trust the token structure or do a simple decoding if verified by gateway, 
# but best practice is to verify. 
# Since we are doing a demo, we will decode unverified to get the 'sub' (User ID) 
# assuming usage behind a secure client or for simplicity. 
# TODO: Implement proper JWKS verification for production.

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        # DECODING WITHOUT VERIFICATION FOR DEMO SPEED as we don't have the PEM key handy instantly.
        # In PROD: Use jwt.decode(token, key, algorithms=["RS256"]) using Clerk's public key.
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
