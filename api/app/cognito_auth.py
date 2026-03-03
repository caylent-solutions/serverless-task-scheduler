"""
Cognito authentication utilities for verifying JWT tokens
"""
import os
import time
from typing import Optional, Dict
from jose import jwk, jwt
from jose.utils import base64url_decode
import requests
import logging

logger = logging.getLogger("app")

JWKS_CONNECT_TIMEOUT_SECONDS = 3
JWKS_READ_TIMEOUT_SECONDS = 5
JWKS_FETCH_MAX_RETRIES = 3


class CognitoTokenVerifier:
    """Verify Cognito JWT tokens"""

    def __init__(self):
        self.region = os.environ.get('COGNITO_REGION', 'us-east-1')
        self.user_pool_id = os.environ.get('COGNITO_USER_POOL_ID', '')
        self.client_id = os.environ.get('COGNITO_CLIENT_ID', '')
        self.keys_url = f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}/.well-known/jwks.json'
        self._keys = None
        self._keys_last_fetched = 0
        self._keys_cache_duration = 3600  # Cache keys for 1 hour

    def _get_keys(self) -> Dict:
        """Fetch and cache public keys from Cognito"""
        current_time = time.time()

        # Return cached keys if still valid
        if self._keys and (current_time - self._keys_last_fetched) < self._keys_cache_duration:
            return self._keys

        last_error = None
        for attempt in range(1, JWKS_FETCH_MAX_RETRIES + 1):
            try:
                response = requests.get(
                    self.keys_url,
                    timeout=(JWKS_CONNECT_TIMEOUT_SECONDS, JWKS_READ_TIMEOUT_SECONDS)
                )
                response.raise_for_status()
                self._keys = response.json()
                self._keys_last_fetched = current_time
                return self._keys
            except requests.RequestException as e:
                last_error = e
                if attempt < JWKS_FETCH_MAX_RETRIES:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

        logger.error(f"Failed to fetch Cognito keys after {JWKS_FETCH_MAX_RETRIES} attempts: {last_error}")
        if self._keys:  # Return stale keys if fetch fails
            return self._keys
        raise RuntimeError("Unable to fetch Cognito JWKS keys") from last_error

    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Verify a Cognito JWT token

        Args:
            token: JWT token to verify

        Returns:
            Decoded token claims if valid, None otherwise
        """
        if not token:
            return None

        if not self.user_pool_id or not self.client_id:
            logger.warning("Cognito configuration not set, skipping token verification")
            return None

        try:
            # Get the key ID from the token header
            headers = jwt.get_unverified_headers(token)
            kid = headers.get('kid')

            if not kid:
                logger.error("Token missing 'kid' header")
                return None

            # Get public keys
            keys = self._get_keys()

            # Find the key that matches the token's kid
            key = None
            for k in keys.get('keys', []):
                if k['kid'] == kid:
                    key = k
                    break

            if not key:
                logger.error(f"Public key not found for kid: {kid}")
                return None

            # Construct the public key
            public_key = jwk.construct(key)

            # Get the message and signature from the token
            message, encoded_signature = token.rsplit('.', 1)
            decoded_signature = base64url_decode(encoded_signature.encode('utf-8'))

            # Verify the signature
            if not public_key.verify(message.encode('utf-8'), decoded_signature):
                logger.error("Token signature verification failed")
                return None

            # Decode the token claims
            claims = jwt.get_unverified_claims(token)

            # Verify token expiration
            if time.time() > claims.get('exp', 0):
                logger.error("Token has expired")
                return None

            # Verify the audience (client ID)
            if claims.get('client_id') != self.client_id and claims.get('aud') != self.client_id:
                logger.error(f"Token audience mismatch. Expected: {self.client_id}")
                return None

            # Verify the issuer
            expected_issuer = f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}'
            if claims.get('iss') != expected_issuer:
                logger.error(f"Token issuer mismatch. Expected: {expected_issuer}")
                return None

            # Verify token use
            if claims.get('token_use') not in ['id', 'access']:
                logger.error(f"Invalid token_use: {claims.get('token_use')}")
                return None

            return claims

        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return None


# Global verifier instance
_verifier = None


def get_token_verifier() -> CognitoTokenVerifier:
    """Get or create the global token verifier instance"""
    global _verifier
    if _verifier is None:
        _verifier = CognitoTokenVerifier()
    return _verifier
