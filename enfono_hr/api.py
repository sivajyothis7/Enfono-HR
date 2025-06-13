import frappe
from frappe import _



@frappe.whitelist(allow_guest=True)
def custom_login(mobile_number=None, password=None):
    try:
        frappe.logger().info(f"Attempting login for mobile number: {mobile_number}")

        if not mobile_number or not password:
            frappe.local.response["http_status_code"] = 404
            frappe.local.response["message"] = _("Invalid mobile number or password.")
            return

        user = frappe.db.get_value("User", {"mobile_no": mobile_number}, ["name", "enabled", "email"], as_dict=True)
        if not user or not user["enabled"]:
            frappe.local.response["http_status_code"] = 404
            frappe.local.response["message"] = _("Invalid mobile number or password.")
            return

        try:
            login_manager = frappe.auth.LoginManager()
            login_manager.authenticate(user=user["email"], pwd=password)
            login_manager.post_login()
        except frappe.exceptions.AuthenticationError:
            frappe.local.response["http_status_code"] = 404
            frappe.local.response["message"] = _("Invalid mobile number or password.")
            return

        user_doc = frappe.get_doc('User', frappe.session.user)
        api_secret = generate_keys(user_doc)

        employee_id = frappe.db.get_value("Employee", {"user_id": user_doc.name})

        if not employee_id:
            frappe.local.response["http_status_code"] = 404
            frappe.local.response["message"] = _("User is not linked to any Employee record.")
            return

        frappe.local.response["message"] = {
            "success_key": 1,
            "message": _("Authentication successful."),
            "sid": frappe.session.sid,
            "username": user_doc.username or user_doc.first_name,
            "email": user_doc.email,
            "mobile_number": user_doc.mobile_no,
            "employee_id": employee_id,
            "api_key": user_doc.api_key,
            "api_secret": api_secret
        }
    except Exception as e:
        frappe.logger().error(f"Login failed for mobile number: {mobile_number}. Error: {str(e)}")
        frappe.local.response["http_status_code"] = 404
        frappe.local.response["message"] = _("Invalid mobile number or password.")





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
        if frappe.session.user == "Guest":
            frappe.local.response["http_status_code"] = 403
            frappe.local.response["message"] = _("You are not logged in.")
            return

        frappe.logger().info(f"Logging out user: {frappe.session.user}")

        frappe.local.login_manager.logout()

        frappe.local.response["message"] = {
            "success_key": 1,
            "message": _("Logged out successfully.")
        }
    except Exception as e:
        frappe.logger().error(f"Logout failed. Error: {str(e)}")
        frappe.local.response["http_status_code"] = 500
        frappe.local.response["message"] = _("Logout failed.")


@frappe.whitelist()
def employee_checkin(employee=None, timestamp=None, latitude=None, longitude=None):
    from frappe.utils import now_datetime

    try:
        if not employee:
            frappe.local.response["http_status_code"] = 400
            frappe.local.response["message"] = _("Missing employee.")
            return

        if latitude is None or longitude is None:
            frappe.local.response["http_status_code"] = 400
            frappe.local.response["message"] = _("Location data (latitude and longitude) is required.")
            return

        if not timestamp:
            timestamp = now_datetime()

        last_checkin = frappe.db.get_all(
            "Employee Checkin",
            filters={"employee": employee},
            fields=["log_type"],
            order_by="creation desc",
            limit=1
        )

        if not last_checkin:
            next_log_type = "IN"
        else:
            last_type = last_checkin[0]["log_type"]
            next_log_type = "OUT" if last_type == "IN" else "IN"

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

        frappe.local.response["message"] = {
            "success_key": 1,
            "message": _("{} recorded successfully.").format(next_log_type),
            "checkin_id": checkin.name,
            "log_type": next_log_type
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Smart Checkin API Error")
        frappe.local.response["http_status_code"] = 500
        frappe.local.response["message"] = _("Failed to record checkin.")
