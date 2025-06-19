import frappe
from frappe.auth import LoginManager
from frappe.utils import now_datetime
from frappe.utils import now_datetime, add_days



@frappe.whitelist(allow_guest=True)
def custom_login(username=None, password=None):
    try:
        def send_response(message, status_code, status_message, **extra_fields):
            frappe.local.response["http_status_code"] = status_code
            frappe.local.response.update({
                "message": message,
                "status_code": status_code,
                "status_message": status_message,
                **extra_fields
            })
            return None 

        if not username or not password:
            return send_response(
                message="Invalid login credentials",
                status_code=401,
                status_message="Invalid username/password"
            )

        user = frappe.db.get_value("User", {"mobile_no": username}, ["name", "enabled", "email"], as_dict=True)
        if not user or not user.enabled:
            return send_response(
                message="Invalid login credentials",
                status_code=401,
                status_message="Invalid username/password"
            )

        try:
            login_manager = LoginManager()
            login_manager.authenticate(user=user["email"], pwd=password)
            login_manager.post_login()
        except frappe.exceptions.AuthenticationError:
            return send_response(
                message="Invalid login credentials",
                status_code=401,
                status_message="Invalid username/password"
            )

        user_doc = frappe.get_doc("User", frappe.session.user)
        api_secret = generate_keys(user_doc)

        employee_id = frappe.db.get_value("Employee", {"user_id": user_doc.name})
        if not employee_id:
            return send_response(
                message="User is not linked to any Employee record.",
                status_code=401,
                status_message="Invalid username/password"
            )

        return send_response(
            message="Authentication successful.",
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
        frappe.local.response["http_status_code"] = 500
        frappe.local.response.update({
            "message": "Something went wrong",
            "status_code": 500,
            "status_message": "Server Error"
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
        def send_response(message, status_code, status_message):
            frappe.local.response["http_status_code"] = status_code
            frappe.local.response.update({
                "message": message,
                "status_code": status_code,
                "status_message": status_message
            })
            return None

        if frappe.session.user == "Guest":
            return send_response(
                message="You are not logged in.",
                status_code=401,
                status_message="Guest user cannot logout"
            )

        frappe.local.login_manager.logout()
        frappe.db.commit()

        return send_response(
            message="Logged out successfully.",
            status_code=200,
            status_message="Logout success"
        )

    except Exception as e:
        frappe.logger().error(f"Logout failed. Error: {str(e)}")
        frappe.local.response["http_status_code"] = 500
        frappe.local.response.update({
            "message": "Something went wrong during logout",
            "status_code": 500,
            "status_message": "Server Error"
        })
        return None



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

        if frappe.session.user == "Guest":
            return send_response(
                message="Authentication required.",
                status_code=401,
                status_message="Unauthorized"
            )

        

        if not employee:
            return send_response(
                message="No employee record linked to the current user.",
                status_code=404,
                status_message="Employee not found"
            )

        if not frappe.db.exists("Employee", employee):
            return send_response(
                message="Invalid employee ID.",
                status_code=404,
                status_message="Employee not found"
            )

        

        if latitude is None or longitude is None:
            return send_response(
                message="Location data is required.",
                status_code=400,
                status_message="Latitude and longitude are mandatory"
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
            message=f"{next_log_type} recorded successfully.",
            status_code=200,
            status_message="Checkin successful",
            checkin_id=checkin.name,
            log_type=next_log_type,
            next_action="Check Out" if next_log_type == "IN" else "Check In"
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Smart Checkin API Error")
        return send_response(
            message="Failed to record checkin.",
            status_code=500,
            status_message="Same Time Log"
        )




@frappe.whitelist(allow_guest=True)
def get_employee_checkins():
    def send_response(message, status_code, status_message, **extra):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "message": message,
            "status_code": status_code,
            "status_message": status_message,
            **extra
        })
        return None

    try:
        if frappe.session.user == "Guest":
            return send_response(
                message="Authentication required.",
                status_code=401,
                status_message="Unauthorized"
            )

        user = frappe.session.user
        employee_id = frappe.db.get_value("Employee", {"user_id": user})
        if not employee_id:
            return send_response(
                message="No employee linked to this user.",
                status_code=404,
                status_message="Employee not found"
            )

        to_date = now_datetime().date()
        from_date = add_days(to_date, -7)

        records = frappe.get_all(
            "Employee Checkin",
            filters={
                "employee": employee_id,
                "time": ["between", [from_date, to_date]]
            },
            fields=["name", "time", "log_type"],
            order_by="time desc"
        )

        return send_response(
            message="Check-ins fetched successfully.",
            status_code=200,
            status_message="Success",
            employee_id=employee_id,
            from_date=str(from_date),
            to_date=str(to_date),
            records=records
        )

    except Exception as e:
        frappe.log_error(str(e), "Checkin Fetch Failed")
        return send_response(
            message="Something went wrong.",
            status_code=500,
            status_message="Internal Server Error"
        )



@frappe.whitelist(allow_guest=True)
def get_last_checkin_status():
    def send_response(message, status_code, status_message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "message": message,
            "status_code": status_code,
            "status_message": status_message,
            **extra_fields
        })
        return None

    try:
        if frappe.session.user == "Guest":
            return send_response(
                message="Authentication required.",
                status_code=401,
                status_message="Unauthorized"
            )

        user = frappe.session.user
        employee_id = frappe.db.get_value("Employee", {"user_id": user})
        if not employee_id:
            return send_response(
                message="No employee linked to this user.",
                status_code=404,
                status_message="Employee not found"
            )

        last_checkin = frappe.db.get_all(
            "Employee Checkin",
            filters={"employee": employee_id},
            fields=["name", "log_type", "time"],
            order_by="creation desc",
            limit=1
        )

        if not last_checkin:
            current_status = "No check-ins yet"
            next_action = "Check In"
        else:
            current_status = last_checkin[0]["log_type"]
            next_action = "Check Out" if current_status == "IN" else "Check In"

        return send_response(
            message="Last check-in status fetched successfully.",
            status_code=200,
            status_message="Success",
            employee_id=employee_id,
            last_log_type=current_status,
            last_checkin_time=str(last_checkin[0]["time"]) if last_checkin else None,
            next_action=next_action
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Fetch Checkin Status Error")
        return send_response(
            message="Failed to fetch last check-in status.",
            status_code=500,
            status_message="Internal Server Error"
        )




@frappe.whitelist(allow_guest=True)
def get_app_version():
    doc = frappe.get_single("App Version Control")

    frappe.local.response.update({
        "status_code": 200,
        "status_message": "Success",
        "latest_android_version": getattr(doc, "latest_android_version", None),
        "latest_ios_version": getattr(doc, "latest_ios_version", None),
        "android_link": getattr(doc, "android_link", None),
        "ios_link": getattr(doc, "ios_link", None)
    })
