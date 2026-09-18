import os
import logging
import json
from boxsdk import OAuth2, Client
import requests

from __init__ import TOKEN_FILE, CLIENT_ID, CLIENT_SECRET, URL_TOKEN


def test_token_refresh():
    """Test function to manually trigger token refresh and check logs."""
    logging.info("Testing token refresh...")
    new_access_token, new_refresh_token = refresh_box_token()

    if new_access_token:
        logging.info("Refresh Token Test: Success ")
    else:
        logging.error("Refresh Token Test: Failed ")


def refresh_box_token():
    """Automatically refresh the Box API token and update stored tokens."""
    access_token, refresh_token = load_tokens()
    if not refresh_token:
        logging.error("No refresh token found. Please initialize it.")
        return None, None
    logging.info("Attempting to refresh Box API token...")

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(URL_TOKEN, data=payload)
    if response.status_code == 200:
        data = response.json()
        new_access_token = data["access_token"]
        new_refresh_token = data["refresh_token"]
        logging.info("Token successfully refreshed.")
        save_tokens(new_access_token, new_refresh_token)
        return new_access_token, new_refresh_token
    else:
        logging.error(f"Failed to refresh Box token: {response.text}")
        return None, None


def save_tokens(access_token, refresh_token):
    """Save the Box API tokens to a file so they persist across runs."""
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)
    print("Tokens updated and saved.")
    logging.info("Box tokens updated and saved to file.")


def load_tokens():
    """Load the Box API tokens from a file if available."""
    if not os.path.exists(TOKEN_FILE):
        logging.error("Token file not found! Please create box_tokens.json.")
        #print("Token file not found! Please create box_tokens.json.")
        return None, None
    try:
        with open(TOKEN_FILE, "r") as f:
            tokens = json.load(f)
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            if not access_token or not refresh_token:
                logging.error("box_tokens.json is missing access_token or refresh_token.")
                #print("box_tokens.json is missing access_token or refresh_token.")
                return None, None
            logging.info(f"Loaded tokens: Access: {access_token[:10]}..., Refresh: {refresh_token[:10]}...")
            #print(f"Loaded tokens: Access: {access_token[:10]}..., Refresh: {refresh_token[:10]}...")
            return access_token, refresh_token
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON: {e}")
        #print(f"Failed to decode JSON: {e}")
        return None, None


def authenticate_box(client_id, client_secret):
    """Authenticates with Box using stored or refreshed tokens."""
    access_token, refresh_token = load_tokens()
    #print(access_token ,"-" , refresh_token)
    if not access_token or not refresh_token:
        logging.error("No valid tokens found. Please initialize them.")
        return None
    oauth2 = OAuth2(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        store_tokens=save_tokens
    )
    return Client(oauth2)