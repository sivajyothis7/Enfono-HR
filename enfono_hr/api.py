import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def custom_login(username=None, password=None):
    try:
        frappe.logger().info(f"Attempting login for username: {username}")

        def send_response(status_code, status_message, **extra_fields):
            frappe.local.response["http_status_code"] = status_code
            frappe.local.response.update({
                "status_code": status_code,
                "status_message": status_message,
                **extra_fields
            })
            return None

        if not username or not password:
            return send_response(
                status_code=401,
                status_message="Invalid username/password"
            )

        user = frappe.db.get_value("User", {"mobile_no": username}, ["name", "enabled", "email"], as_dict=True)
        if not user or not user["enabled"]:
            return send_response(
                status_code=401,
                status_message="Invalid username/password"
            )

        try:
            login_manager = frappe.auth.LoginManager()
            login_manager.authenticate(user=user["email"], pwd=password)
            login_manager.post_login()

            for key in ["message", "home_page", "full_name"]:
                frappe.local.response.pop(key, None)

        except frappe.exceptions.AuthenticationError:
            return send_response(
                status_code=401,
                status_message="Invalid username/password"
            )

        user_doc = frappe.get_doc("User", frappe.session.user)
        api_secret = generate_keys(user_doc)

        employee_id = frappe.db.get_value("Employee", {"user_id": user_doc.name})
        if not employee_id:
            return send_response(
                status_code=401,
                status_message="Invalid username/password"
            )

        return send_response(
            status_code=200,
            status_message="Login success",
            sid=frappe.session.sid,
            email=user_doc.email,
            mobile_number=user_doc.mobile_no,
            employee_id=employee_id,
            api_key=user_doc.api_key,
            api_secret=api_secret
        )

    except Exception as e:
        frappe.logger().error(f"Login failed for username: {username}. Error: {str(e)}")
        frappe.local.response["http_status_code"] = 401
        frappe.local.response.update({
            "status_code": 401,
            "status_message": "Invalid username/password"
        })
        return None


def generate_keys(user):
    """
    Generate API Key and API Secret for the user if they don't already exist.
    """
    api_secret = frappe.generate_hash(length=15)
    if not user.api_key:
        user.api_key = frappe.generate_hash(length=15)

    user.api_secret = api_secret
    user.save(ignore_permissions=True)

    frappe.logger().info(f"Generated API Key: {user.api_key}, API Secret: {api_secret}")
    return api_secret


@frappe.whitelist(allow_guest=True)
def custom_logout():
    try:
        def send_response(status_code, status_message, message):
            frappe.local.response["http_status_code"] = status_code
            frappe.local.response.update({
                "message": message,
                "status_code": status_code,
                "status_message": status_message
            })

        if frappe.session.user == "Guest":
            return send_response(
                status_code=401,
                status_message="Guest user cannot logout",
                message="You are not logged in."
            )

        frappe.logger().info(f"Logging out user: {frappe.session.user}")
        frappe.local.login_manager.logout()

        return send_response(
            status_code=200,
            status_message="Logout success",
            message="Logged out successfully."
        )

    except Exception as e:
        frappe.logger().error(f"Logout failed. Error: {str(e)}")
        return send_response(
            status_code=500,
            status_message="Server error during logout",
            message="Logout failed."
        )


@frappe.whitelist()
def employee_checkin(employee=None, timestamp=None, latitude=None, longitude=None):
    try:
        def send_response(status_code, status_message, message, **extra_fields):
            frappe.local.response["http_status_code"] = status_code
            frappe.local.response.update({
                "message": message,
                "status_code": status_code,
                "status_message": status_message,
                **extra_fields
            })

        if not employee:
            return send_response(
                status_code=401,
                status_message="Employee ID is required",
                message="Missing employee."
            )

        if latitude is None or longitude is None:
            return send_response(
                status_code=401,
                status_message="Latitude and longitude are mandatory",
                message="Location data is required."
            )

        if not timestamp:
            timestamp = now_datetime()

        last_checkin = frappe.db.get_all(
            "Employee Checkin",
            filters={"employee": employee},
            fields=["log_type"],
            order_by="creation desc",
            limit=1
        )

        next_log_type = "IN" if not last_checkin else (
            "OUT" if last_checkin[0]["log_type"] == "IN" else "IN"
        )

        checkin = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee,
            "log_type": next_log_type,
            "time": timestamp,
            "latitude": latitude,
            "longitude": longitude
        })
        checkin.insert(ignore_permissions=True)
        frappe.db.commit()

        return send_response(
            status_code=200,
            status_message="Checkin successful",
            message=f"{next_log_type} recorded successfully.",
            checkin_id=checkin.name,
            log_type=next_log_type
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Smart Checkin API Error")
        return send_response(
            status_code=500,
            status_message="Same Time Log",
            message="Failed to record checkin."
        )
