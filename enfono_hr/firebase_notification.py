import json
import requests
import frappe
from frappe import enqueue
from google.oauth2 import service_account
from google.auth.transport import requests as google_requests
from frappe.utils import now, add_to_date
import re

def cleanhtml(raw_html):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext


def user_id(doc):
    user_email = doc.for_user
    user_device_id = frappe.get_all(
        "User Devices", filters={"user": user_email}, fields=["device_token"]
    )
    return user_device_id

@frappe.whitelist()

def notification_queue(doc,method):
    device_token = user_id(doc)
    frappe.log_error(f"Device Token: {device_token}", "FCM Debugging")
    if device_token:
        for device in device_token:
            enqueue(
                send_notification,
                queue="default",
                now=False,
                device_token=device,
                notification=doc
            )

 

def get_fcm_credentials():
    credentials_doc = frappe.get_single("Firebase Notification Settings")
    private_key = credentials_doc.get_password("private_key")
    if private_key:
        private_key = private_key.replace("\\n", "\n").strip()  # converts \n to actual newlines

    service_account_info = {
        "type": "service_account",
        "project_id": credentials_doc.get("project_id"),
        "private_key_id": credentials_doc.get("private_key_id"),
        "private_key": private_key,
        "client_email": credentials_doc.get("client_email"),
        "client_id": credentials_doc.get("client_id"),
        "auth_uri": credentials_doc.get("auth_uri"),
        "token_uri": credentials_doc.get("token_uri"),
        "auth_provider_x509_cert_url": credentials_doc.get("auth_provider_x509_cert_url"),
        "client_x509_cert_url": credentials_doc.get("client_x509_cert_url")
    }
    return service_account_info


@frappe.whitelist()
def get_cached_access_token():
    """
    Retrieves the cached access token if valid, otherwise generates a new one.
    """
    try:
        credentials_doc = frappe.get_single("Firebase Notification Settings")
        
        if credentials_doc.access_token and credentials_doc.expiration_time > now():
            return {"access_token": credentials_doc.get_password("access_token")}

        service_account_info = get_fcm_credentials()
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )

        frappe.log_error(f"Credentials: {credentials}", "FCM Credentials Object")

        request = google_requests.Request()
        credentials.refresh(request)
        
        frappe.log_error(f"Refreshed Credentials: {credentials}", "FCM Credentials Object")

        access_token = credentials.token
        expiration_time = add_to_date(now(), minutes=55)

        credentials_doc.access_token = access_token
        credentials_doc.expiration_time = expiration_time
        credentials_doc.save()
        frappe.db.commit()


        return {"access_token": access_token}
    
    except Exception as e:
        frappe.log_error(f"Error in get_cached_access_token: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def send_notification(notification, device_token):
    """
    Sends a push notification using the cached access token.
    """

    frappe.log_error(f"Notification: {notification}", "FCM Debugging")

    # Ensure device_token is a string
    if isinstance(device_token, dict):
        device_token = device_token.get("device_token", "")
    elif not isinstance(device_token, str):
        device_token = str(device_token)

    frappe.log_error(f"Device Token: {device_token[:50]}", "FCM Debugging")

    body = notification.email_content if hasattr(notification, "email_content") else ""
    title = notification.subject if hasattr(notification, "subject") else ""

    body = cleanhtml(body)
    title = cleanhtml(title)

    access_token = get_cached_access_token()

    headers = {
        "Authorization": f'Bearer {access_token["access_token"]}',
        "Content-Type": "application/json; UTF-8",
    }

    payload = {
        "message": {
            "token": device_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "android": {
                "notification": {
                    "sound": "cash_notification.wav"
                }
            },
            "apns": {
                "payload": {
                    "aps": {
                        "sound": "cash_notification.wav"
                    }
                }
            },
            "data": {
                "doctype": getattr(notification, "document_type", ""),
                "docname": str(getattr(notification, "document_name", "")),
            }
        }
    }

    frappe.log_error(f"Payload sent: {json.dumps(payload, indent=2)}", "FCM Debugging")

    fcm_endpoint = f'https://fcm.googleapis.com/v1/projects/{get_fcm_credentials()["project_id"]}/messages:send'
    response = requests.post(fcm_endpoint, headers=headers, json=payload)

    if response.status_code == 200:
        frappe.log_error(f"Notification sent successfully: {response.json()}", "FCM Debugging")
        return {"status": "success", "response": response.json()}
    else:
        error_message = f"Failed to send notification: {response.text}"
        frappe.log_error(error_message, "FCM Notification Error")
        return {"status": "failed", "error": error_message}
