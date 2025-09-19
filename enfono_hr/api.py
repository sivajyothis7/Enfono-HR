import frappe
from frappe.auth import LoginManager
from frappe.utils import now_datetime,getdate
from frappe.utils import now_datetime, add_days
import json
import random
import requests
from frappe.utils.password import update_password
from urllib.parse import quote_plus
import re
from frappe.utils import getdate, date_diff, nowdate
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from frappe.model.workflow import apply_workflow
from frappe.utils.file_manager import save_file
import base64
from frappe.utils.file_manager import save_file
from frappe.utils import now_datetime
from math import radians, cos, sin, asin, sqrt
from frappe.utils.pdf import get_pdf
from frappe.utils import today




#####Login#####

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

        employee_doc = frappe.get_doc("Employee", {"user_id": user_doc.name})
        if not employee_doc:
            return send_response(
                message="User is not linked to any Employee record.",
                status_code=401,
                status_message="Invalid username/password"
            )

        def get_user_full_name(user_id):
            if not user_id:
                return None
            return frappe.db.get_value("User", user_id, "full_name")

        expense_approver = employee_doc.get("expense_approver")
        shift_request_approver = employee_doc.get("shift_request_approver")
        leave_approver = employee_doc.get("leave_approver")

        user_roles = frappe.get_roles(user_doc.name)

        if "HR Manager" in user_roles:
            user_type = "hr_manager"
        elif "Leave Approver" in user_roles:
            user_type = "leave_approver"
        else:
            user_type = "employee"

        return send_response(
            message="Authentication successful.",
            status_code=200,
            status_message="Login success",
            sid=frappe.session.sid,
            email=user_doc.email,
            mobile_number=user_doc.mobile_no,
            employee_id=employee_doc.name,
            api_key=user_doc.api_key,
            api_secret=api_secret,
            expense_approver_name=get_user_full_name(expense_approver),
            shift_request_approver_name=get_user_full_name(shift_request_approver),
            leave_approver_name=get_user_full_name(leave_approver),
            user_type=user_type
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

#####Post Checkin#####

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

####Geo-fencing


@frappe.whitelist()
def geo_employee_checkin(employee=None, timestamp=None, latitude=None, longitude=None):
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

        employee_doc = frappe.get_doc("Employee", employee)

        if not employee_doc:
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

        if not employee_doc.get("custom_disable_geo_fencing"):
            allowed_locations = frappe.get_all(
                "Employee Allowed Location",
                filters={"parent": employee, "parenttype": "Employee"},
                fields=["latitude", "longitude"]
            )

            if not allowed_locations:
                return send_response(
                    message="No allowed geolocations configured for this employee.",
                    status_code=400,
                    status_message="Missing location config"
                )

            def haversine(lat1, lon1, lat2, lon2):
                R = 6371000
                dlat = radians(lat2 - lat1)
                dlon = radians(lon2 - lon1)
                a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
                c = 2 * asin(sqrt(a))
                return R * c

            within_range = any(
                haversine(float(latitude), float(longitude), float(loc.latitude), float(loc.longitude)) <= 30
                for loc in allowed_locations
            )

            if not within_range:
                return send_response(
                    message="You are not within the allowed check-in area (30m radius).",
                    status_code=403,
                    status_message="Out of range"
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
            status_message="Server Error"
        )


#####Checkin Records#####

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

#####Last Checkin Status#####

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


#####APP Version#####

@frappe.whitelist(allow_guest=True)
def get_app_version():
    doc = frappe.get_single("App Version Control")

    if frappe.request.method == "POST":
        android_version = frappe.form_dict.get("latest_android_version")
        ios_version = frappe.form_dict.get("latest_ios_version")

        if android_version:
            doc.latest_android_version = android_version
        if ios_version:
            doc.latest_ios_version = ios_version

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.local.response.update({
            "status_code": 200,
            "status_message": "Updated Successfully",
            "latest_android_version": doc.latest_android_version,
            "latest_ios_version": doc.latest_ios_version
        })

    else:
        frappe.local.response.update({
            "status_code": 200,
            "status_message": "Success",
            "latest_android_version": doc.latest_android_version,
            "latest_ios_version": doc.latest_ios_version,
            "android_link": doc.android_link,
            "ios_link": doc.ios_link
        })



#####Shift Type List#####

@frappe.whitelist(allow_guest=True)
def get_available_shift_types():
    try:
        shift_types = frappe.get_all(
            "Shift Type",
            fields=["name", "start_time", "end_time"]
        )

        frappe.local.response["http_status_code"] = 200
        frappe.local.response.update({
            "status_code": 200,
            "status_message": "Success",
            "message": "Shift types fetched successfully.",
            "shift_types": [
                {
                    "name": s.name,
                    "start_time": str(s.start_time),
                    "end_time": str(s.end_time)
                } for s in shift_types
            ]
        })
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Fetch Shift Types Error")
        frappe.local.response["http_status_code"] = 500
        frappe.local.response.update({
            "status_code": 500,
            "status_message": "Error",
            "message": "Failed to fetch shift types.",
            "shift_types": []
        })

#####Create Shift Request#####


@frappe.whitelist()
def create_shift_request(shift_type, from_date, to_date):
    from frappe.utils import getdate, nowdate

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "You must be logged in.")

        if not shift_type or not from_date or not to_date:
            return send_response(400, "Missing Fields", "Shift Type, From Date, and To Date are mandatory.")

        from_date = getdate(from_date)
        to_date = getdate(to_date)
        today = getdate(nowdate())

        if from_date > to_date:
            return send_response(400, "Invalid Dates", "From Date cannot be after To Date.")

        if from_date < today:
            return send_response(400, "Invalid Dates", "Shift request cannot start in the past.")

        if not frappe.db.exists("Shift Type", shift_type):
            return send_response(400, "Invalid", f"Shift Type '{shift_type}' does not exist.")

        employee = frappe.db.get_value("Employee", {"user_id": user})
        if not employee:
            return send_response(404, "Not Found", "No Employee record linked to the user.")

        approver = frappe.db.get_value("Employee", employee, "shift_request_approver")
        if not approver:
            return send_response(400, "Missing Approver", "No Shift Request Approver assigned for this employee. Please contact HR.")

        default_shift = frappe.db.get_value("Employee", employee, "default_shift")
        if default_shift == shift_type:
            return send_response(400, "Invalid Shift", "You cannot request your default shift.")

        overlapping = frappe.db.sql("""
            SELECT name FROM `tabShift Request`
            WHERE employee = %s
              AND status IN ('Approved', 'Draft')
              AND (from_date <= %s AND to_date >= %s)
        """, (employee, to_date, from_date))
        if overlapping:
            return send_response(409, "Conflict", "This shift request overlaps with an existing request.")

        doc = frappe.get_doc({
            "doctype": "Shift Request",
            "employee": employee,
            "shift_type": shift_type,
            "from_date": from_date,
            "to_date": to_date,
            "shift_request_approver": approver,
            "status": "Draft"
        })
        doc.insert()
        frappe.db.commit()

        return send_response(
            200,
            "Success",
            "Shift request created successfully.",
            request_id=doc.name,
            shift_type=doc.shift_type,
            from_date=str(doc.from_date),
            to_date=str(doc.to_date),
            status=doc.status
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Shift Request Creation Failed")
        return send_response(500, "Error", "Something went wrong.")


#####Employee Shift Requests List####

@frappe.whitelist()
def get_my_shift_requests():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        employee_id = frappe.db.get_value("Employee", {"user_id": user})
        if not employee_id:
            return send_response(404, "Not Found", "No employee linked to this user.")

        employee_doc = frappe.get_doc("Employee", employee_id)
        shift_request_approver = employee_doc.get("shift_request_approver")

        def get_user_full_name(user_id):
            return frappe.db.get_value("User", user_id, "full_name") if user_id else None

        shift_request_approver_name = get_user_full_name(shift_request_approver)

        shift_requests_raw = frappe.get_all(
            "Shift Request",
            filters={"employee": employee_id},
            fields=["name", "shift_type", "from_date", "to_date", "status", "creation"],
            order_by="creation desc"
        )

        shift_requests = []
        for req in shift_requests_raw:
            req["shift_request_approver_name"] = shift_request_approver_name
            shift_requests.append(req)

        return send_response(
            200,
            "Success",
            "Shift requests fetched.",
            shift_requests=shift_requests
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get My Shift Requests Failed")
        return send_response(500, "Error", "Something went wrong.")


######Team Shift Requests List#####
@frappe.whitelist()
def get_team_shift_requests():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Login required.")

        shift_requests = []

        current_employee = frappe.db.get_value("Employee", {"user_id": user})

        employees = frappe.get_all("Employee", filters={"shift_request_approver": user}, pluck="name")

        if current_employee and current_employee in employees:
            employees.remove(current_employee)

        if employees:
            approver_reqs = frappe.get_all(
                "Shift Request",
                filters={"employee": ["in", employees]},
                fields=[
                    "name", "employee", "shift_type", "from_date",
                    "to_date", "workflow_state", "creation"
                ],
                order_by="creation desc"
            )
            shift_requests.extend(approver_reqs)

        if "HR Manager" in frappe.get_roles(user):
            hr_reqs = frappe.get_all(
                "Shift Request",
                filters={"workflow_state": "Approval Pending By HR"},
                fields=[
                    "name", "employee", "shift_type", "from_date",
                    "to_date", "workflow_state", "creation"
                ],
                order_by="creation desc"
            )
            shift_requests.extend(hr_reqs)

        for req in shift_requests:
            req["employee_name"] = frappe.db.get_value("Employee", req["employee"], "employee_name")

        return send_response(200, "Success", "Team shift requests fetched.", shift_requests=shift_requests)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Team Shift Requests Failed")
        return send_response(500, "Error", "Something went wrong.")


#####Approve_or_reject_shift_request#####

@frappe.whitelist()
def approve_or_reject_shift_request(shift_request_id, action):
    from frappe.model.workflow import apply_workflow

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        valid_actions = [
            "Approve and Forward",
            "Reject",
            "Approve",
            "Cancel"
        ]

        if action not in valid_actions:
            return send_response(400, "Invalid Action", f"Action must be one of: {', '.join(valid_actions)}")

        doc = frappe.get_doc("Shift Request", shift_request_id)

        employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
        if employee_user == user:
            return send_response(403, "Forbidden", "You cannot approve or reject your own shift request.")

        user_roles = frappe.get_roles(user)
        current_state = doc.workflow_state

        if action == "Approve and Forward":
            if "Leave Approver" not in user_roles:
                return send_response(403, "Forbidden", "Only Leave Approvers can approve and forward.")
            if current_state != "Open":
                return send_response(400, "Invalid State", "This action is allowed only in 'Open' state.")

        elif action == "Approve":
            if "HR Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only HR Managers can approve.")
            if current_state != "Approval Pending By HR":
                return send_response(400, "Invalid State", "This action is allowed only in 'Approval Pending By HR' state.")

        elif action == "Reject":
            if current_state == "Open" and "Leave Approver" not in user_roles:
                return send_response(403, "Forbidden", "Only Leave Approvers can reject at this stage.")
            elif current_state == "Approval Pending By HR" and "HR Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only HR Managers can reject at this stage.")

        elif action == "Cancel":
            if "System Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only System Managers can cancel shift requests.")

        apply_workflow(doc, action)
        frappe.db.commit()

        return send_response(200, "Success", f"Shift request updated with action '{action}'.", shift_request_id=doc.name)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Shift Request Workflow Failed")
        return send_response(500, "Error", "Something went wrong.")

#####LEAVE APPLICATION API####

######View Leave Types#####

@frappe.whitelist(allow_guest=True)
def get_available_leave_types():
    try:
        leave_types = frappe.get_all(
            "Leave Type",
            fields=["name", "max_leaves_allowed"]
        )

        frappe.local.response["http_status_code"] = 200
        frappe.local.response.update({
            "status_code": 200,
            "status_message": "Success",
            "message": "Leave types fetched successfully.",
            "leave_types": leave_types
        })

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Fetch Leave Types Error")
        frappe.local.response["http_status_code"] = 500
        frappe.local.response.update({
            "status_code": 500,
            "status_message": "Error",
            "message": "Failed to fetch leave types.",
            "leave_types": []
        })



######Create Leave Requests#####


@frappe.whitelist()
def create_leave_application(leave_type, from_date, to_date, half_day=None, half_day_date=None, reason=None):

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Login required.")

        if not leave_type or not from_date or not to_date:
            return send_response(400, "Missing Fields", "Leave type, from date and to date are required.")

        employee = frappe.db.get_value("Employee", {"user_id": user})
        if not employee:
            return send_response(404, "Not Found", "No employee linked to the user.")

        if not frappe.db.exists("Leave Type", leave_type):
            return send_response(400, "Invalid", "Leave type does not exist.")

        from_dt = getdate(from_date)
        to_dt = getdate(to_date)

        if from_dt > to_dt:
            return send_response(400, "Invalid Dates", "From date cannot be after to date.")

        if half_day and half_day_date:
            half_dt = getdate(half_day_date)
            if not (from_dt <= half_dt <= to_dt):
                return send_response(400, "Invalid Half Day Date", "Half-day date must be within the leave date range.")

        is_lwp = frappe.db.get_value("Leave Type", leave_type, "is_lwp")
        allocation_required = not is_lwp

        if allocation_required:
            allocation = frappe.db.exists("Leave Allocation", {
                "employee": employee,
                "leave_type": leave_type,
                "from_date": ["<=", to_date],
                "to_date": [">=", from_date],
                "docstatus": 1
            })

            if not allocation:
                return send_response(400, "Leave Not Allocated", f"Leave type '{leave_type}' is not allocated. Please contact HR.")

            leave_balance = get_leave_balance_on(employee, leave_type, from_date)
            requested_days = 0.5 if half_day else date_diff(to_date, from_date) + 1

            if leave_balance < requested_days:
                return send_response(400, "Insufficient Leave Balance", f"Only {leave_balance} day(s) available, but {requested_days} day(s) requested.")

        overlap = frappe.db.sql("""
            SELECT name FROM `tabLeave Application`
            WHERE employee = %s AND docstatus < 2 AND status != 'Rejected'
              AND (from_date <= %s AND to_date >= %s)
        """, (employee, to_date, from_date))
        if overlap:
            return send_response(409, "Conflict", "Leave application overlaps with an existing one.")

        leave_approver = frappe.db.get_value("Employee", employee, "leave_approver")
        if not leave_approver:
            return send_response(400, "Missing Approver", "No leave approver is assigned to your profile. Please contact HR.")

        doc = frappe.get_doc({
            "doctype": "Leave Application",
            "employee": employee,
            "leave_type": leave_type,
            "from_date": from_date,
            "to_date": to_date,
            "half_day": half_day,
            "half_day_date": half_day_date if half_day else None,
            "leave_approver": leave_approver,
            "workflow_state": "Open",
            "description": reason
        })
        doc.insert()
        frappe.db.commit()

        return send_response(200, "Success", "Leave application submitted.", application_id=doc.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Leave Application Failed for user: {user}")
        return send_response(500, "Error", "Something went wrong.")


######Employee Leave Requests List#####

@frappe.whitelist()
def get_my_leave_applications():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Login required.")

        employee = frappe.db.get_value("Employee", {"user_id": user})
        if not employee:
            return send_response(404, "Not Found", "No employee linked.")

        leave_apps_raw = frappe.get_all(
            "Leave Application",
            filters={"employee": employee},
            fields=["name", "leave_type", "from_date", "to_date", "workflow_state", "creation", "leave_approver"],
            order_by="creation desc"
        )

        def get_user_full_name(user_id):
            return frappe.db.get_value("User", user_id, "full_name") if user_id else None

        leave_apps = []
        for app in leave_apps_raw:
            leave_apps.append({
                "name": app.name,
                "leave_type": app.leave_type,
                "from_date": app.from_date,
                "to_date": app.to_date,
                "workflow_state": app.workflow_state,
                "creation": app.creation,
                "leave_approver_name": get_user_full_name(app.leave_approver)
            })

        return send_response(200, "Success", "Leave applications fetched.", leave_applications=leave_apps)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Leave Applications Failed")
        return send_response(500, "Error", "Something went wrong.")



######Team Leave Requests List#####


@frappe.whitelist()
def get_team_leave_applications():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Login required.")

        leave_apps = []

        current_employee = frappe.db.get_value("Employee", {"user_id": user})

        employees = frappe.get_all("Employee", filters={"leave_approver": user}, pluck="name")

        if current_employee and current_employee in employees:
            employees.remove(current_employee)

        if employees:
            approver_apps = frappe.get_all(
                "Leave Application",
                filters={"employee": ["in", employees]},
                fields=[
                    "name", "employee", "leave_type", "from_date",
                    "to_date", "workflow_state", "creation"
                ],
                order_by="creation desc"
            )
            leave_apps.extend(approver_apps)

        if "HR Manager" in frappe.get_roles(user):
            hr_apps = frappe.get_all(
                "Leave Application",
                filters={"workflow_state": "Approval Pending By HR"},
                fields=[
                    "name", "employee", "leave_type", "from_date",
                    "to_date", "workflow_state", "creation"
                ],
                order_by="creation desc"
            )
            leave_apps.extend(hr_apps)

        for app in leave_apps:
            app["employee_name"] = frappe.db.get_value("Employee", app["employee"], "employee_name")

        return send_response(200, "Success", "Team leave applications fetched.", leave_applications=leave_apps)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Team Leave Applications Failed")
        return send_response(500, "Error", "Something went wrong.")


######Approve Leave Requests List#####



@frappe.whitelist()
def approve_or_reject_leave_application(application_id, action):
    from frappe.model.workflow import apply_workflow

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        valid_actions = [
            "Approve and Forward",
            "Reject",
            "Approve",
            "Cancel"
        ]

        if action not in valid_actions:
            return send_response(400, "Invalid Action", f"Action must be one of: {', '.join(valid_actions)}")

        doc = frappe.get_doc("Leave Application", application_id)

        employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
        if employee_user == user:
            return send_response(403, "Forbidden", "You cannot approve or reject your own leave.")

        user_roles = frappe.get_roles(user)
        current_state = doc.workflow_state

        if action == "Approve and Forward":
            if "Leave Approver" not in user_roles:
                return send_response(403, "Forbidden", "Only Leave Approvers can approve and forward.")
            if current_state != "Open":
                return send_response(400, "Invalid State", "This action is allowed only in 'Open' state.")

        elif action == "Approve":
            if "HR Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only HR Managers can approve.")
            if current_state != "Approval Pending By HR":
                return send_response(400, "Invalid State", "This action is allowed only in 'Approval Pending By HR' state.")

        elif action == "Reject":
            if current_state == "Open" and "Leave Approver" not in user_roles:
                return send_response(403, "Forbidden", "Only Leave Approvers can reject at this stage.")
            elif current_state == "Approval Pending By HR" and "HR Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only HR Managers can reject at this stage.")

        elif action == "Cancel":
            if "System Manager" not in user_roles:
                return send_response(403, "Forbidden", "Only System Managers can cancel leave.")

        apply_workflow(doc, action)
        frappe.db.commit()

        return send_response(200, "Success", f"Leave application updated with action '{action}'.", application_id=doc.name)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Leave Approval Workflow Failed")
        return send_response(500, "Error", "Something went wrong.")


#####Attendance Request#####



@frappe.whitelist()
def create_attendance_request(from_date, to_date, reason, half_day=False, half_day_date=None):

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        employee = frappe.db.get_value("Employee", {"user_id": user})
        if not employee:
            return send_response(404, "Not Found", "No employee linked to this user.")

        if not from_date or not to_date or not reason:
            return send_response(400, "Bad Request", "From Date, To Date, and Reason are required.")

        from_date = getdate(from_date)
        to_date = getdate(to_date)

        if from_date > to_date:
            return send_response(400, "Invalid Dates", "From Date cannot be after To Date.")

        if half_day and not half_day_date:
            return send_response(400, "Missing Field", "Half Day Date is required if Half Day is selected.")
        
        if half_day and (getdate(half_day_date) < from_date or getdate(half_day_date) > to_date):
            return send_response(400, "Invalid Date", "Half Day Date must be within the request range.")

        if frappe.db.exists("Attendance Request", {
            "employee": employee,
            "from_date": ["<=", to_date],
            "to_date": [">=", from_date],
            "docstatus": ["!=", 2]  
        }):
            return send_response(409, "Conflict", "Overlapping attendance request already exists.")

        valid_dates = []
        holiday_list = frappe.db.get_value("Employee", employee, "holiday_list") or ""

        for i in range((to_date - from_date).days + 1):
            day = add_days(from_date, i)

            if frappe.db.exists("Attendance", {
                "employee": employee,
                "attendance_date": day,
                "docstatus": ["<", 2]
            }):
                continue

            leave = frappe.db.sql("""
                SELECT name FROM `tabLeave Application`
                WHERE employee = %s AND docstatus = 1
                  AND status NOT IN ('Rejected', 'Cancelled')
                  AND from_date <= %s AND to_date >= %s
            """, (employee, day, day))
            if leave:
                continue

            if holiday_list and frappe.db.exists("Holiday", {
                "parent": holiday_list,
                "holiday_date": day
            }):
                continue

            valid_dates.append(day)

        if not valid_dates:
            return send_response(400, "No Valid Dates", "No attendance records can be created. All dates fall on leave, holidays, or already marked.")

        doc = frappe.get_doc({
            "doctype": "Attendance Request",
            "employee": employee,
            "from_date": from_date,
            "to_date": to_date,
            "reason": reason,
            "half_day": half_day,
            "half_day_date": getdate(half_day_date) if half_day else None
        })
        doc.insert()
        frappe.db.commit()

        return send_response(200, "Success", "Attendance request created.", request_id=doc.name)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Attendance Request Creation Failed")
        return send_response(500, "Error", "Something went wrong.")


####Forgot Password- OTP####



DIGIMILES_LOGIN_URL = 'http://sms.digimiles.in/bulksms/bulksms'
DIGIMILES_USERNAME = 'di78-enfono'  
DIGIMILES_PASSWORD = 'digimile'
DIGIMILES_SOURCE = 'ENFONO'
DIGIMILES_TEMPLATE_ID = '1607100000000142881'
DIGIMILES_ENTITY_ID = '1601421163066783668'
DIGIMILES_TM_ID = '1601421163066783668,1602100000000009244'  

DIGIMILES_OTP_TEMPLATE = (
    "Dear Customer, Your One Time Password is {#var#} and valid for 10 mins. "
    "Do not share to anyone. Team, Enfono Technology."
)

DIGIMILES_RESPONSE_CODES = {
    "1701": "Message submitted successfully",
    "1702": "Invalid URL Error",
    "1703": "Invalid username or password",
    "1704": "Invalid 'type' field value",
    "1705": "Invalid Message",
    "1706": "Invalid Destination number",
    "1707": "Invalid Source (Sender ID)",
    "1708": "Invalid DLR value",
    "1709": "User validation failed",
    "1710": "Internal Error",
    "1025": "Invalid or missing template ID",
    "2904": "Template mismatch (Hash/Chain Not Match)",
    "2905": "DLT Failed: Blocked or Format Issue",
    "2906": "Invalid Entity ID",
    "2907": "Invalid PE ID",
    "2908": "Template not linked to Sender ID",
    "2910": "DLT parameters missing or incorrect"
}

def build_sms_url(mobile_no, message):
    encoded_msg = quote_plus(message)
    return (
        f"{DIGIMILES_LOGIN_URL}?"
        f"username={DIGIMILES_USERNAME}&password={DIGIMILES_PASSWORD}&"
        f"type=0&dlr=1&destination={mobile_no}&"
        f"source={DIGIMILES_SOURCE}&message={encoded_msg}&"
        f"entityid={DIGIMILES_ENTITY_ID}&tempid={DIGIMILES_TEMPLATE_ID}&"
        f"tmid={DIGIMILES_TM_ID}"
    )



@frappe.whitelist(allow_guest=True)
def send_otp(mobile_no):
    mobile_no = mobile_no.strip()

    if not mobile_no:
        frappe.local.response["http_status_code"] = 400
        frappe.response["message"] = "Mobile number is required"
        frappe.response["status_code"] = 400
        return

    if not re.fullmatch(r'[6-9]\d{9}', mobile_no):
        frappe.local.response["http_status_code"] = 400
        frappe.response["message"] = "Invalid mobile number format"
        frappe.response["status_code"] = 400
        return

    user_id = frappe.db.get_value("User", {"mobile_no": mobile_no})
    if not user_id:
        frappe.local.response["http_status_code"] = 404
        frappe.response["message"] = "Mobile number not registered"
        frappe.response["status_code"] = 404
        frappe.response["mobile_no"] = mobile_no
        return

    otp = str(random.randint(1000, 9999))  
    message = DIGIMILES_OTP_TEMPLATE.replace("{#var#}", otp)
    url = build_sms_url(mobile_no, message)

    try:
        response = requests.get(url, timeout=10)
        response_text = response.text.strip()
        frappe.logger().info(f"Digimiles response for {mobile_no}: {response.status_code} - {response_text}")

        response_code = response_text.split('|')[0]

        if response_code != "1701":
            error_message = DIGIMILES_RESPONSE_CODES.get(response_code, "Unknown error from Digimiles")
            frappe.local.response["http_status_code"] = 500
            frappe.response["message"] = f"Failed to send OTP: {error_message}"
            frappe.response["digimiles_response"] = response_text
            frappe.response["status_code"] = 500
            frappe.response["mobile_no"] = mobile_no
            return

        frappe.cache().set_value(f"otp:{mobile_no}", otp, expires_in_sec=600)

        frappe.local.response["http_status_code"] = 200
        frappe.response["message"] = "OTP sent successfully"
        frappe.response["status_code"] = 200
        frappe.response["mobile_no"] = mobile_no
        return

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Digimiles OTP Send Failed")
        frappe.local.response["http_status_code"] = 500
        frappe.response["message"] = "Internal error while sending OTP"
        frappe.response["status_code"] = 500
        frappe.response["mobile_no"] = mobile_no
        return


@frappe.whitelist(allow_guest=True)
def verify_and_reset_password(mobile_no, otp, new_password=None, confirm_password=None):
    mobile_no = mobile_no.strip()
    otp = otp.strip()

    if not (mobile_no and otp):
        frappe.local.response["http_status_code"] = 400
        frappe.response["message"] = "Mobile number and OTP are required"
        frappe.response["status_code"] = 400
        return

    cached_otp = frappe.cache().get_value(f"otp:{mobile_no}")
    if not cached_otp:
        frappe.local.response["http_status_code"] = 410
        frappe.response["message"] = "OTP expired or not found"
        frappe.response["status_code"] = 410
        return

    if cached_otp != otp:
        frappe.local.response["http_status_code"] = 401
        frappe.response["message"] = "Invalid OTP"
        frappe.response["status_code"] = 401
        return

    if not new_password:
        frappe.cache().set_value(f"otp_verified:{mobile_no}", True, expires_in_sec=600)
        frappe.local.response["http_status_code"] = 200
        frappe.response["message"] = "OTP verified"
        frappe.response["status_code"] = 200
        return

    is_verified = frappe.cache().get_value(f"otp_verified:{mobile_no}")
    if not is_verified:
        frappe.local.response["http_status_code"] = 403
        frappe.response["message"] = "OTP not verified"
        frappe.response["status_code"] = 403
        return

    if not confirm_password or new_password != confirm_password:
        frappe.local.response["http_status_code"] = 422
        frappe.response["message"] = "Passwords do not match"
        frappe.response["status_code"] = 422
        return

    user_id = frappe.db.get_value("User", {"mobile_no": mobile_no})
    if not user_id:
        frappe.local.response["http_status_code"] = 404
        frappe.response["message"] = "User not found"
        frappe.response["status_code"] = 404
        return

    update_password(user_id, new_password)

    frappe.cache().delete_value(f"otp:{mobile_no}")
    frappe.cache().delete_value(f"otp_verified:{mobile_no}")

    frappe.local.response["http_status_code"] = 200
    frappe.response["message"] = "Password reset successful"
    frappe.response["status_code"] = 200




######CRM######

###Lead Creation

@frappe.whitelist()
def create_lead(
    first_name,
    company_name,
    status,
    lead_source=None,
    email=None,
    phone=None,
    mobile_no=None,
    whatsapp_no=None,
    website=None,
    remarks=None,
    gender=None,
    request_type=None,
    city=None,
    state=None,
    country=None
):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        if not first_name:
            return send_response(400, "Invalid", "First Name is required.")
        if not company_name:
            return send_response(400, "Invalid", "Organization Name is required.")
        if not status:
            return send_response(400, "Invalid", "Status is required.")

        valid_status = ["Lead", "Open", "Replied", "Interested", "Converted", "Do Not Contact"]
        valid_gender = ["Male", "Female", "Other"]
        valid_request_type = [
            "Product Enquiry",
            "Catalogue Enquiry",
            "Measurement",
            "Remeasurement",
            "Fitting",
            "Refitting",
            "Rectification",
            "Stitching",
            "Request for Information",
            "Suggestions",
            "Other"
        ]

        if status not in valid_status:
            return send_response(400, "Invalid", "Invalid status.")
        if gender and gender not in valid_gender:
            return send_response(400, "Invalid", "Invalid gender.")
        if request_type and request_type not in valid_request_type:
            return send_response(400, "Invalid", "Invalid request type.")
        if email and not frappe.utils.validate_email_address(email):
            return send_response(400, "Invalid", "Invalid email address.")

        duplicate_conditions = []
        if email:
            duplicate_conditions.append(("email_id", "=", email))
        if mobile_no:
            duplicate_conditions.append(("mobile_no", "=", mobile_no))

        if duplicate_conditions:
            existing_lead = frappe.db.exists("Lead", duplicate_conditions)
            if existing_lead:
                return send_response(
                    409, "Duplicate", "A lead with this email or mobile number already exists.",
                    existing_lead_id=existing_lead
                )

        doc = frappe.get_doc({
            "doctype": "Lead",
            "first_name": first_name,
            "company_name": company_name,
            "status": status,
            "lead_source": lead_source,
            "lead_owner": user,
            "email_id": email,
            "phone": phone,
            "mobile_no": mobile_no,
            "whatsapp_no": whatsapp_no,
            "website": website,
            "remarks": remarks,
            "gender": gender,
            "request_type": request_type,
            "city": city,
            "state": state,
            "country": country
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return send_response(200, "Success", "Lead created successfully.", lead_id=doc.name)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Create Lead Failed")
        return send_response(500, "Error", "Failed to create lead.")


#####Lead Detailed View

@frappe.whitelist()
def get_lead_details(lead_name=None):
    def send_response(message, status_code, status_message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if not user or user == "Guest":
            return send_response("Please log in first.", 401, "Unauthorized")

        if not lead_name:
            return send_response("'lead_name' is required.", 400, "Bad Request")

        if not frappe.db.exists("Lead", lead_name):
            return send_response(f"Lead '{lead_name}' not found.", 404, "Not Found")

        lead = frappe.get_doc("Lead", lead_name)

        todos = frappe.get_all("ToDo",
            filters={
                "reference_type": "Lead",
                "reference_name": lead_name,
                "status": ["!=", "Cancelled"]
            },
            fields=["owner", "assigned_by"]
        )

        assigned_to = list({
            frappe.db.get_value("User", t.owner, "full_name") or t.owner
            for t in todos if t.owner != lead.owner
        })

        assigned_by = None
        for t in todos:
            if t.assigned_by:
                assigned_by = frappe.db.get_value("User", t.assigned_by, "full_name") or t.assigned_by
                break

        base_url = frappe.utils.get_url()

        attachments = frappe.get_all("File",
            filters={
                "attached_to_doctype": "Lead",
                "attached_to_name": lead_name
            },
            fields=["file_url", "file_name"]
        )

        for att in attachments:
            if att.get("file_url"):
                att["file_url"] = base_url + att["file_url"]

        lead_data = {
            "name": lead.name,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "date": lead.custom_date,
            "updated_date": lead.updated_date,
            "company_name": lead.company_name,
            "status": lead.status,
            "lead_source": lead.lead_source,
            "request_type": lead.request_type,
            "email_id": lead.email_id,
            "phone": lead.phone,
            "mobile_no": lead.mobile_no,
            "whatsapp_no": lead.whatsapp_no,
            "website": lead.website,
            "remarks": lead.remarks,
            "gender": lead.gender,
            "city": lead.city,
            "state": lead.state,
            "country": lead.country,
            "lead_owner": frappe.db.get_value("User", lead.owner, "full_name") or lead.owner,
            "assigned_to": assigned_to,
            "assigned_by": assigned_by,
            "attachments": attachments
        }

        return send_response(
            f"Lead '{lead_name}' details fetched.",
            200,
            "Success",
            lead=lead_data
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get Lead Details Failed")
        return send_response("Could not fetch lead details.", 500, "Error")



#####View My Leads#####

@frappe.whitelist()
def get_my_leads():
    def send_response(message, status_code, status_message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        if not frappe.session.user or frappe.session.user == "Guest":
            return send_response("Please log in first.", 401, "Unauthorized")

        user = frappe.session.user

        owned_leads = frappe.get_all("Lead",
            filters={"owner": user},
            fields=[
                "name", "custom_date","updated_date","first_name", "last_name", "company_name", "location", "latitude", "longitude",
                "status", "request_type", "email_id", "phone", "mobile_no", "remarks",
                "whatsapp_no", "city", "state", "country", "creation"
            ],
             order_by="modified desc"
        )
        owned_lead_names = [lead["name"] for lead in owned_leads]

        assigned_todos_on_owned = frappe.get_all("ToDo",
            filters={
                "reference_type": "Lead",
                "reference_name": ["in", owned_lead_names],
                "status": ["!=", "Cancelled"]
            },
            fields=["reference_name", "allocated_to"]
        )
        assigned_map = {}
        for todo in assigned_todos_on_owned:
            assigned_map.setdefault(todo.reference_name, []).append(todo.allocated_to)

        for lead in owned_leads:
            lead["source"] = "Owner"
            assigned_emails = assigned_map.get(lead["name"], [])
            assigned_full_names = [
                frappe.db.get_value("User", email, "full_name") or email
                for email in assigned_emails
            ]
            lead["assigned_to"] = assigned_full_names

            if lead.get("latitude") and lead.get("longitude"):
                lat = lead["latitude"]
                lon = lead["longitude"]
                lead["google_maps_link"] = f"https://www.google.com/maps?q={lat},{lon}"

        assigned_todos = frappe.get_all("ToDo",
            filters={
                "reference_type": "Lead",
                "allocated_to": user,
                "status": ["!=", "Cancelled"]
            },
            fields=["reference_name"]
        )
        assigned_lead_names = [d.reference_name for d in assigned_todos]

        assigned_leads = []
        if assigned_lead_names:
            leads = frappe.get_all("Lead",
                filters=[
                    ["name", "in", assigned_lead_names],
                    ["owner", "!=", user]
                ],
                fields=[
                    "name", "custom_date","updated_date","first_name", "last_name", "company_name", "location", "latitude", "longitude",
                    "status", "request_type", "email_id", "phone", "mobile_no", "whatsapp_no",
                    "city", "state", "country", "creation", "owner"
                ]
            )
            for lead in leads:
                lead["source"] = "Assigned"
                lead["assigned_by"] = frappe.db.get_value("User", lead["owner"], "full_name") or lead["owner"]

                if lead.get("latitude") and lead.get("longitude"):
                    lat = lead["latitude"]
                    lon = lead["longitude"]
                    lead["google_maps_link"] = f"https://www.google.com/maps?q={lat},{lon}"

            assigned_leads = leads

        all_leads = owned_leads + assigned_leads

        if not all_leads:
            return send_response("No leads found.", 200, "Success", leads=[])

        return send_response("Your leads fetched.", 200, "Success", leads=all_leads)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "get_my_leads")
        return send_response("Could not retrieve leads.", 500, "Error")



#####Modify Leads####

@frappe.whitelist()
def update_lead(lead_id, **kwargs):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        lead = frappe.get_doc("Lead", lead_id)
        # if lead.lead_owner != user:
        #     return send_response(403, "Forbidden", "You do not have permission to modify this lead.")

        editable_fields = [
            "first_name", "last_name","custom_date","updated_date","company_name", "status","lead_source", "email_id", "phone",
            "mobile_no", "whatsapp_no", "website", "remarks", "gender",
            "request_type", "city", "state"
        ]

        valid_status = ["Lead", "Open", "Replied","Opportunity" ,"Quotation","Lost Quotation", "Interested","Converted", "Do Not Contact"]
        valid_gender = ["Male", "Female", "Other"]
        valid_request_type = ["Product Enquiry", "Catalogue Enquiry", "Measurement","Remeasurement", "Fitting","Refitting", "Rectification","Stitching","Request for Information", "Suggestions", "Other"]

        for field, value in kwargs.items():
            if field in editable_fields:
                if field == "status" and value not in valid_status:
                    return send_response(400, "Invalid", "Invalid status.")
                if field == "gender" and value not in valid_gender:
                    return send_response(400, "Invalid", "Invalid gender.")
                if field == "request_type" and value not in valid_request_type:
                    return send_response(400, "Invalid", "Invalid request type.")
                if field == "email_id" and value and not frappe.utils.validate_email_address(value):
                    return send_response(400, "Invalid", "Invalid email address.")
                lead.set(field, value)

        lead.save(ignore_permissions=True)
        frappe.db.commit()

        return send_response(200, "Success", "Lead updated successfully.", lead_id=lead.name)

    except frappe.DoesNotExistError:
        return send_response(404, "Not Found", f"Lead with ID '{lead_id}' not found.")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Update Lead Failed")
        return send_response(500, "Error", "Failed to update lead.")


####Delete My Lead####

@frappe.whitelist()
def delete_my_lead(lead_id):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user

        if user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        if "Sales User" not in frappe.get_roles(user):
            return send_response(403, "Forbidden", "Only users with the 'Sales User' role can delete leads.")

        lead = frappe.get_doc("Lead", lead_id)

        if lead.lead_owner != user:
            return send_response(403, "Forbidden", "You are not allowed to delete this lead.")

        lead.delete()
        frappe.db.commit()

        return send_response(200, "Success", f"Lead {lead_id} deleted successfully.")

    except frappe.DoesNotExistError:
        return send_response(404, "Not Found", f"Lead with ID '{lead_id}' does not exist.")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Delete Lead Failed")
        return send_response(500, "Error", "Could not delete lead.")


#######Asssign Lead#######

@frappe.whitelist()
def get_assignable_users():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        users = frappe.get_all(
            "User",
            filters={
                "enabled": 1,
                "user_type": "System User",
                "name": ["!=", "Administrator"]
            },
            fields=["full_name"]
        )

        full_names = [user.full_name for user in users if user.full_name]

        return send_response(
            200,
            "Success",
            "User full names fetched successfully.",
            users=full_names
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Fetch User Full Names Failed")
        return send_response(500, "Error", "Unable to fetch user full names.")


####Assign Lead 

@frappe.whitelist()
def assign_lead_to_user(lead_name=None, full_name=None):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if frappe.session.user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        if not lead_name or not full_name:
            return send_response(400, "Bad Request", "Both 'lead_name' and 'full_name' are required.")

        if not frappe.db.exists("Lead", lead_name):
            return send_response(404, "Not Found", f"Lead '{lead_name}' not found.")

        user_id = frappe.db.get_value("User", {"full_name": full_name}, "name")
        if not user_id:
            return send_response(404, "Not Found", f"No user found with name '{full_name}'.")

        existing_todo = frappe.get_all("ToDo", 
            filters={
                "allocated_to": user_id,
                "reference_type": "Lead",
                "reference_name": lead_name,
                "status": ["!=", "Cancelled"]
            },
            limit=1
        )

        if existing_todo:
            return send_response(409, "Conflict", f"Lead '{lead_name}' is already assigned to '{full_name}'.")

        frappe.get_doc({
            "doctype": "ToDo",
            "allocated_to": user_id,
            "reference_type": "Lead",
            "reference_name": lead_name,
            "description": f"Lead assigned to {full_name}",
            "status": "Open"  
        }).insert(ignore_permissions=True)

        frappe.db.commit()

        return send_response(200, "Success", f"Lead '{lead_name}' assigned to '{full_name}'.")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Lead Assignment Failed")
        return send_response(500, "Error", "Something went wrong while assigning the lead.")

### Search Leads

@frappe.whitelist()
def search_leads(searchText=None):
    def send_response(message, status_code, status_message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        if not frappe.session.user or frappe.session.user == "Guest":
            return send_response("Please log in first.", 401, "Unauthorized")

        if not searchText:
            return send_response("Please provide searchText (phone, mobile, or first name).", 400, "Bad Request")

        user = frappe.session.user

        fields = [
            "name", "first_name", "last_name", "company_name", "location", "latitude", "longitude",
            "status", "request_type", "email_id", "phone", "mobile_no", "whatsapp_no", "remarks",
            "city", "state", "country", "creation", "owner"
        ]

        owned_leads = frappe.get_list(
            "Lead",
            filters={"owner": user},
            or_filters={
                "phone": ["like", f"%{searchText}%"],
                "mobile_no": ["like", f"%{searchText}%"],
                "first_name": ["like", f"%{searchText}%"]
            },
            fields=fields,
            order_by="modified desc"
        )

        assigned_leads = frappe.get_list(
            "Lead",
            filters={"_assign": ["like", f"%{user}%"]},
            or_filters={
                "phone": ["like", f"%{searchText}%"],
                "mobile_no": ["like", f"%{searchText}%"],
                "first_name": ["like", f"%{searchText}%"]
            },
            fields=fields,
            order_by="modified desc"
        )

        leads_map = {lead["name"]: lead for lead in (owned_leads + assigned_leads)}
        leads = list(leads_map.values())

        for lead in leads:
            if lead.get("latitude") and lead.get("longitude"):
                lat, lon = lead["latitude"], lead["longitude"]
                lead["google_maps_link"] = f"https://www.google.com/maps?q={lat},{lon}"

        if not leads:
            return send_response("No leads found.", 200, "Success", leads=[])

        return send_response("Leads fetched successfully.", 200, "Success", leads=leads)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "search_leads")
        return send_response("Could not search leads.", 500, "Error")


########Create Customer from Lead#####


@frappe.whitelist()
def create_customer_from_lead(lead_name):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if frappe.session.user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        if not frappe.db.exists("Lead", lead_name):
            return send_response(404, "Not Found", "Lead does not exist.")

        lead = frappe.get_doc("Lead", lead_name)

        existing_customer = frappe.db.exists("Customer", {"lead_name": lead.name})
        if existing_customer:
            return send_response(409, "Conflict", "Customer already created for this lead.", customer_id=existing_customer)

        customer = frappe.new_doc("Customer")
        customer.customer_name = lead.lead_name
        customer.customer_type = "Individual" if not lead.company_name else "Company"
        customer.lead_name = lead.name
        customer.territory = lead.country 
        customer.insert()
        frappe.db.commit()

        return send_response(200, "Success", "Customer created successfully.", customer_id=customer.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Customer from Lead Failed")
        return send_response(500, "Error", "Something went wrong while creating the customer.")




######Quotation from Lead

@frappe.whitelist()
def create_quotation_from_lead(lead_name, description, rate):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if frappe.session.user == "Guest":
            return send_response(401, "Unauthorized", "Please login first.")

        if not lead_name or not description or rate is None:
            return send_response(400, "Bad Request", "Lead, description, and rate are required.")

        if not frappe.db.exists("Lead", lead_name):
            return send_response(404, "Not Found", "Lead does not exist.")

        lead = frappe.get_doc("Lead", lead_name)

        customer_name = frappe.db.get_value("Customer", {"lead_name": lead.name}, "name")

        quotation = frappe.new_doc("Quotation")
        quotation.quotation_to = "Lead" if not customer_name else "Customer"
        quotation.party_name = lead.name if not customer_name else customer_name
        quotation.lead = lead.name
        quotation.transaction_date = nowdate()
        quotation.status = "Draft"

        quotation.append("items", {        

            "item_code": "Services",
            "item_name": "Services",
            "description": description,
            "qty": 1,
            "rate": float(rate)
        })

        quotation.insert()
        frappe.db.commit()

        return send_response(
            200,
            "Success",
            "Quotation created successfully.",
            quotation_id=quotation.name
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Quotation from Lead Failed")
        return send_response(500, "Error", "Something went wrong while creating the quotation.")



##### Quotations created by the logged-in user

@frappe.whitelist()
def get_quotations_by_user():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.message_log = []
        frappe.local.response.pop("_server_messages", None)
        frappe.local.response.update({
            "http_status_code": status_code,
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        user = frappe.session.user
        if user == "Guest":
            frappe.throw("You must be logged in to access this resource.")

        lead_name = frappe.form_dict.get("lead_name")
        base_url = frappe.utils.get_url()

        if lead_name:
            filters = {"party_name": lead_name}
        else:
            assigned_quotations = frappe.get_all(
                "ToDo",
                filters={
                    "reference_type": "Quotation",
                    "owner": user
                },
                pluck="reference_name"
            )

            owned_quotations = frappe.get_all(
                "Quotation",
                filters={"owner": user},
                pluck="name"
            )

            all_quotation_names = list(set(assigned_quotations + owned_quotations))

            if not all_quotation_names:
                return send_response(
                    200,
                    "Success",
                    "No quotations found.",
                    data=[]
                )

            filters = {"name": ["in", all_quotation_names]}

        quotations = frappe.get_all(
            "Quotation",
            filters=filters,
            fields=[
                "name", "party_name", "customer_name",
                "quotation_to", "transaction_date", "status", "grand_total"
            ],
            order_by="modified desc"
        )

        for quotation in quotations:
            attachments = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Quotation",
                    "attached_to_name": quotation["name"]
                },
                fields=["file_url", "file_name"]
            )

            for att in attachments:
                if att.get("file_url"):
                    att["file_url"] = base_url + att["file_url"]

            quotation["attachments"] = attachments

        return send_response(
            200,
            "Success",
            "Quotations fetched successfully.",
            data=quotations
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get Quotations by User Failed")
        return send_response(
            500,
            "Failed",
            "An error occurred while fetching quotations.",
            data=[]
        )

########Geolocation


@frappe.whitelist()
def create_lead_geolocation(lead_name, latitude=None, longitude=None):
	def send_response(status_code, status_message, message, **extra_fields):
		frappe.local.response["http_status_code"] = status_code
		frappe.local.response.update({
			"status_code": status_code,
			"status_message": status_message,
			"message": message,
			**extra_fields
		})
		return None

	def reverse_geocode(lat, lon):
		try:
			response = requests.get(
				"https://nominatim.openstreetmap.org/reverse",
				params={"format": "json", "lat": lat, "lon": lon},
				headers={"User-Agent": "frappe-app"}
			)
			if response.status_code == 200:
				return response.json().get("display_name")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Reverse Geocoding Failed")
		return ""

	try:
		if frappe.session.user == "Guest":
			return send_response(401, "Unauthorized", "Please login first.")

		if not frappe.db.exists("Lead", lead_name):
			return send_response(404, "Not Found", "Lead not found.")

		if not latitude or not longitude:
			return send_response(400, "Bad Request", "Latitude and Longitude are required.")

		lead = frappe.get_doc("Lead", lead_name)
		lead.latitude = latitude
		lead.longitude = longitude
		lead.location = reverse_geocode(latitude, longitude)

		lead.geolocation = frappe.json.dumps({
			"type": "FeatureCollection",
			"features": [
				{
					"type": "Feature",
					"properties": {},
					"geometry": {
						"type": "Point",
						"coordinates": [float(longitude), float(latitude)]
					}
				}
			]
		})

		lead.save(ignore_permissions=True)
		frappe.db.commit()

		return send_response(
			200, "Success", "Geolocation updated successfully.",
			lead=lead.name,
			latitude=latitude,
			longitude=longitude,
			location=lead.location
		)

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Update Lead Geolocation Error")
		return send_response(500, "Error", "Something went wrong while updating geolocation.")



#####Attachments####


@frappe.whitelist(allow_guest=True)
def upload_lead_attachment():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        data = frappe.local.form_dict

        lead_name = data.get("lead_name")
        files = data.get("files") 

        if not lead_name:
            return send_response(400, "Bad Request", "Missing lead_name")

        if not files or not isinstance(files, list):
            return send_response(400, "Bad Request", "Missing or malformed files list")

        results = []
        for file_obj in files:
            file_name = file_obj.get("file_name")
            file_base64 = file_obj.get("file_base64")
            res = {"file_name": file_name}

            if not file_name or not file_base64:
                res["status"] = "failed"
                res["error"] = "Missing file_name or file_base64"
            else:
                try:
                    if file_base64.startswith("data:"):
                        file_base64 = file_base64.split(",", 1)[1]
                    file_base64 = file_base64.strip()
                    missing_padding = len(file_base64) % 4
                    if missing_padding:
                        file_base64 += "=" * (4 - missing_padding)
                    file_data = base64.b64decode(file_base64)

                    saved_file = save_file(
                        file_name,
                        file_data,
                        "Lead",
                        lead_name,
                        folder="Home/Attachments",
                        decode=False
                    )
                    res["status"] = "success"
                    res["file_url"] = saved_file.file_url
                except Exception as file_exc:
                    res["status"] = "failed"
                    res["error"] = str(file_exc)

            results.append(res)

        frappe.db.commit()
        return send_response(200, "Success", "Files uploaded successfully", results=results)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Lead File Upload Error (Batch)")
        return send_response(500, "Error", "Something went wrong during upload")



#####Quotation Attachment

@frappe.whitelist(allow_guest=True)
def upload_quotation_attachment():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        data = frappe.local.form_dict

        quotation_name = data.get("quotation_name")
        files = data.get("files")

        if not quotation_name:
            return send_response(400, "Bad Request", "Missing quotation_name")

        if not files or not isinstance(files, list):
            return send_response(400, "Bad Request", "Missing or malformed files list")

        results = []
        for file_obj in files:
            file_name = file_obj.get("file_name")
            file_base64 = file_obj.get("file_base64")
            res = {"file_name": file_name}

            if not file_name or not file_base64:
                res["status"] = "failed"
                res["error"] = "Missing file_name or file_base64"
            else:
                try:
                    if file_base64.startswith("data:"):
                        file_base64 = file_base64.split(",", 1)[1]
                    file_base64 = file_base64.strip()
                    missing_padding = len(file_base64) % 4
                    if missing_padding:
                        file_base64 += "=" * (4 - missing_padding)
                    file_data = base64.b64decode(file_base64)

                    saved_file = save_file(
                        file_name,
                        file_data,
                        "Quotation",
                        quotation_name,
                        folder="Home/Attachments",
                        decode=False
                    )
                    res["status"] = "success"
                    res["file_url"] = saved_file.file_url
                except Exception as file_exc:
                    res["status"] = "failed"
                    res["error"] = str(file_exc)

            results.append(res)

        frappe.db.commit()
        return send_response(200, "Success", "Files uploaded successfully", results=results)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Quotation File Upload Error (Batch)")
        return send_response(500, "Error", "Something went wrong during upload")


##Monthly Attendance View


from datetime import timedelta
import frappe

@frappe.whitelist()
def get_monthly_attendance(employee=None, year=None, month=None):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if not employee or not year or not month:
            return send_response(400, "Bad Request", "Employee, year and month are required.")

        try:
            year = int(year)
            month = int(month)
        except ValueError:
            return send_response(400, "Bad Request", "Year and month must be valid integers.")

        start_date = f"{year}-{month:02d}-01"
        end_date = frappe.utils.get_last_day(start_date)

        attendance = frappe.get_all(
            "Attendance",
            filters={
                "employee": employee,
                "attendance_date": ["between", [start_date, end_date]]
            },
            fields=["attendance_date", "status"]
        )

        attendance_dates = {frappe.utils.getdate(a["attendance_date"]) for a in attendance}

        leave_apps = frappe.get_all(
            "Leave Application",
            filters={
                "employee": employee,
                "status": "Approved",
                "from_date": ["<=", end_date],
                "to_date": [">=", start_date]
            },
            fields=["from_date", "to_date", "status"]
        )

        leave_dates = set()
        for leave in leave_apps:
            if leave["status"] != "Approved":
                continue
            from_date = frappe.utils.getdate(leave["from_date"])
            to_date = frappe.utils.getdate(leave["to_date"])
            for i in range((to_date - from_date).days + 1):
                d = from_date + timedelta(days=i)
                leave_dates.add(d)

        final_leave_dates = leave_dates - attendance_dates

        for d in final_leave_dates:
            attendance.append({"attendance_date": d, "status": "On Leave"})

        if not attendance:
            return send_response(
                200,
                "Success",
                "No attendance records found for the given month.",
                employee=employee,
                year=year,
                month=month,
                attendance=[]
            )

        seen = set()
        unique_attendance = []
        for record in sorted(attendance, key=lambda x: x["attendance_date"]):
            date_obj = frappe.utils.getdate(record["attendance_date"])
            if date_obj not in seen:
                unique_attendance.append(record)
                seen.add(date_obj)

        return send_response(
            200,
            "Success",
            "Monthly attendance fetched successfully.",
            employee=employee,
            year=year,
            month=month,
            attendance=unique_attendance
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Monthly Attendance Failed")
        return send_response(500, "Error", "Unable to fetch monthly attendance due to a server error.")



## Salary Slip


@frappe.whitelist(allow_guest=True)
def list_salary_slips():
    employee = frappe.form_dict.get("employee")

    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if not employee:
            return send_response(400, "Bad Request", "Employee ID is required.")

        slips = frappe.get_all(
            "Salary Slip",
            filters={
                "employee": employee,
                # "docstatus": 1   # uncomment if you want only submitted
            },
            fields=[
                "name", "employee", "employee_name", "start_date", "end_date",
                "net_pay", "gross_pay", "status"
            ],
            order_by="start_date desc"
        )

        if not slips:
            return send_response(
                200,
                "Success",
                "No submitted salary slips found for this employee.",
                employee=employee,
                salary_slips=[]
            )

        base_url = "https://inlite.enfonoerp.com"

        for slip in slips:
            slip["pdf_url"] = (
                f"{base_url}/printview?"
                f"doctype=Salary Slip"
                f"&name={slip['name']}"
                f"&trigger_print=1"
                f"&format=Salary Slip"
                f"&no_letterhead=0"
                f"&_lang=en"
            )

        return send_response(
            200,
            "Success",
            "Submitted salary slips fetched successfully.",
            employee=employee,
            salary_slips=slips
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Salary Slips Failed")
        return send_response(500, "Error", "Unable to fetch salary slips.")


##List Expense claim

import frappe
from frappe.utils import get_url

@frappe.whitelist()
def list_my_expense_claims():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        user = frappe.session.user

        employee = frappe.db.get_value("Employee", {"user_id": user})
        if not employee:
            return send_response(404, "Not Found", "No employee linked to the current user.")

        claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": employee},
            fields=["name", "posting_date", "total_claimed_amount","total_sanctioned_amount",  "status"],
            order_by="posting_date desc"
        )

        if not claims:
            return send_response(
                200,
                "Success",
                "No expense claims found.",
                employee=employee,
                expense_claims=[]
            )

        base_url = get_url()  

        for claim in claims:
            attachments = frappe.get_all(
                "File",
                filters={"attached_to_doctype": "Expense Claim", "attached_to_name": claim.name},
                fields=["file_name", "file_url"]
            )
            for att in attachments:
                att["file_url"] = f"{base_url}{att['file_url']}"
            claim["attachments"] = attachments

        return send_response(
            200,
            "Success",
            "Expense claims fetched successfully.",
            employee=employee,
            expense_claims=claims
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "List My Expense Claims Failed")
        return send_response(500, "Error", "Unable to fetch expense claims.")



## Create Expense Claim


@frappe.whitelist()
def create_expense_claim(name=None, employee=None,  expenses=None):
    
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if not all([employee, expenses]):
            return send_response(400, "Bad Request", "Employee, company, posting_date and expenses are required.")

        if not isinstance(expenses, list):
            return send_response(400, "Bad Request", "Expenses must be a list of objects.")

        if name:
            claim = frappe.get_doc("Expense Claim", name)
            if claim.docstatus == 1:
                return send_response(400, "Error", "Cannot edit submitted/approved expense claim.")

            claim.expenses = []  
            for item in expenses:
                claim.append("expenses", item)

            claim.save()
        else:
            claim = frappe.get_doc({
                "doctype": "Expense Claim",
                "employee": employee,
            })
            for item in expenses:
                claim.append("expenses", item)
            claim.insert()

        

        frappe.db.commit()

        return send_response(
            200,
            "Success",
            "Expense claim saved successfully.",
            expense_claim=claim.name
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Save Expense Claim Failed")
        return send_response(500, "Error", "Unable to save expense claim.")


### Detailed View

@frappe.whitelist()
def get_expense_claim_detail():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        name = frappe.form_dict.get("name")

        if not name:
            return send_response(400, "Bad Request", "Expense Claim name is required.")

        claim = frappe.get_doc("Expense Claim", name)

        expenses_detail = []
        for exp in claim.expenses:
            expenses_detail.append({
                "expense_date": exp.expense_date,
                "expense_type": exp.expense_type,
                "description": exp.description,
                "amount": exp.amount,
            })

        return send_response(
            200,
            "Success",
            "Expense claim detail fetched successfully.",
            data={
                "name": claim.name,
                "employee": claim.employee,
                "total_claimed_amount": claim.total_claimed_amount,
                "total_sanctioned_amount": claim.total_sanctioned_amount,
                "status": claim.status,
                "posting_date": claim.posting_date,
                "expenses": expenses_detail
            }
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get Expense Claim Detail Failed")
        return send_response(500, "Error", "Unable to fetch expense claim detail.")

### Update Expense Claim


@frappe.whitelist()
def update_expense_claim(name, employee=None, expenses=None):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        if not name:
            return send_response(400, "Bad Request", "Expense Claim name is required.")

        claim = frappe.get_doc("Expense Claim", name)

        if claim.docstatus == 1:
            return send_response(400, "Error", "Cannot edit submitted/approved expense claim.")

        if employee:
            claim.employee = employee

        if expenses:
            if not isinstance(expenses, list):
                return send_response(400, "Bad Request", "Expenses must be a list of objects.")
            claim.expenses = []
            for item in expenses:
                claim.append("expenses", item)

        claim.save(ignore_permissions=True)
        frappe.db.commit()

        expenses_detail = []
        for exp in claim.expenses:
            expenses_detail.append({
                "expense_type": exp.expense_type,
                "description": exp.description,
                "amount": exp.amount,
            })

        return send_response(
            200,
            "Success",
            "Expense claim updated successfully.",
            data={
                "name": claim.name,
                "employee": claim.employee,
                "total_claimed_amount": claim.total_claimed_amount,
                "total_sanctioned_amount": claim.total_sanctioned_amount,
                "status": claim.status,
                "expenses": expenses_detail
            }
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Update Expense Claim Failed")
        return send_response(500, "Error", "Unable to update expense claim.")



### Upload Claim Attachment

import base64
from frappe.utils.file_manager import save_file

@frappe.whitelist(allow_guest=True)
def upload_expense_claim_attachment():
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })

    try:
        data = frappe.local.form_dict

        expense_claim_name = data.get("expense_claim_name")
        files = data.get("files")

        if not expense_claim_name:
            return send_response(400, "Bad Request", "Missing expense_claim_name")

        if not files or not isinstance(files, list):
            return send_response(400, "Bad Request", "Missing or malformed files list")

        results = []
        for file_obj in files:
            file_name = file_obj.get("file_name")
            file_base64 = file_obj.get("file_base64")
            res = {"file_name": file_name}

            if not file_name or not file_base64:
                res["status"] = "failed"
                res["error"] = "Missing file_name or file_base64"
            else:
                try:
                    if file_base64.startswith("data:"):
                        file_base64 = file_base64.split(",", 1)[1]
                    file_base64 = file_base64.strip()
                    missing_padding = len(file_base64) % 4
                    if missing_padding:
                        file_base64 += "=" * (4 - missing_padding)
                    file_data = base64.b64decode(file_base64)

                    saved_file = save_file(
                        file_name,
                        file_data,
                        "Expense Claim",
                        expense_claim_name,
                        folder="Home/Attachments",
                        decode=False
                    )
                    res["status"] = "success"
                    res["file_url"] = saved_file.file_url
                except Exception as file_exc:
                    res["status"] = "failed"
                    res["error"] = str(file_exc)

            results.append(res)

        frappe.db.commit()
        return send_response(200, "Success", "Files uploaded successfully", results=results)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Expense Claim File Upload Error")
        return send_response(500, "Error", "Something went wrong during upload")

        

## List Payment Advance


@frappe.whitelist()
def list_my_payment_advances(name=None):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user})
        if not employee:
            return send_response(404, "Not Found", "No employee found or linked to current user.")

        if name:
            advance = frappe.get_doc("Employee Advance", name)

            if advance.employee != employee and "HR Manager" not in frappe.get_roles(frappe.session.user):
                return send_response(403, "Forbidden", "You are not allowed to view this advance.")

            advance_data = frappe.db.get_value(
                "Employee Advance",
                advance.name,
                ["name", "employee_name","posting_date","purpose", "advance_amount", "paid_amount", "status" ],
                as_dict=True
            )

            return send_response(
                200, "Success", "Payment advance fetched successfully.",
                payment_advance=advance_data
            )

        else:
            advances = frappe.get_all(
                "Employee Advance",
                filters={"employee": employee},
                fields=["name", "posting_date", "purpose","advance_amount", "paid_amount", "status"],
                order_by="posting_date desc"
            )

            if not advances:
                return send_response(200, "Success", "No payment advances found.", payment_advances=[])

            return send_response(
                200, "Success", "Payment advances fetched successfully.",
                payment_advances=advances
            )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Payment Advances API Failed")
        return send_response(500, "Error", "Unable to fetch payment advances.")



### Create Payment Advance


@frappe.whitelist(allow_guest=False)
def create_employee_advance(**kwargs):
    """
    Create an Employee Advance.
    Limit: Cannot exceed 30% of monthly salary (calculated from yearly CTC in Employee profile).
    repay_unclaimed_amount_from_salary → defaults to 1
    """
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        data = kwargs or frappe.form_dict
        if isinstance(data, str):
            import json
            data = json.loads(data)

        employee = data.get("employee")
        if not employee:
            user = frappe.session.user
            employee = frappe.db.get_value("Employee", {"user_id": user})

        if not employee:
            return send_response(404, "Not Found", "No employee specified or linked to current user.")

        advance_amount = data.get("advance_amount")
        if not advance_amount:
            return send_response(400, "Bad Request", "Advance amount is required.")

        try:
            advance_amount = float(advance_amount)
        except:
            return send_response(400, "Bad Request", "Invalid advance amount.")

        yearly_ctc = frappe.db.get_value("Employee", employee, "ctc")
        if not yearly_ctc:
            return send_response(400, "Bad Request", "Employee CTC is not set in profile.")

        monthly_salary = yearly_ctc / 12
        max_advance = monthly_salary * 0.3

        if advance_amount > max_advance:
            return send_response(
                400,
                "Bad Request",
                f"Advance amount cannot exceed 30% of monthly salary. "
                f"Max allowed: {max_advance:.2f}"
            )

        exchange_rate = data.get("exchange_rate")
        try:
            exchange_rate = float(exchange_rate)
            if exchange_rate <= 0:
                exchange_rate = 1
        except:
            exchange_rate = 1

        advance = frappe.new_doc("Employee Advance")
        advance.employee = employee
        advance.posting_date = data.get("posting_date") or today()
        advance.advance_amount = advance_amount
        advance.purpose = data.get("purpose") or "Employee Advance"
        advance.exchange_rate = exchange_rate  

        if hasattr(advance, "repay_unclaimed_amount_from_salary"):
            advance.repay_unclaimed_amount_from_salary = 1

        advance.insert(ignore_permissions=True)
        frappe.db.commit()

        return send_response(
            201,
            "Success",
            "Employee Advance created successfully.",
            employee_advance=advance.name
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Create Employee Advance Failed")
        return send_response(500, "Error", "Unable to create employee advance.")

## Update Payment Advance

@frappe.whitelist(allow_guest=False)
def update_employee_advance(name, posting_date=None, purpose=None, advance_amount=None):
    def send_response(status_code, status_message, message, **extra_fields):
        frappe.local.response["http_status_code"] = status_code
        frappe.local.response.update({
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            **extra_fields
        })
        return None

    try:
        doc = frappe.get_doc("Employee Advance", name)

        if posting_date:
            doc.posting_date = posting_date
        if purpose:
            doc.purpose = purpose
        if advance_amount:
            try:
                doc.advance_amount = float(advance_amount)
            except:
                return send_response(400, "Bad Request", "Invalid advance amount.")

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        advance_data = {
            "name": doc.name,
            "posting_date": doc.posting_date,
            "purpose": doc.purpose,
            "advance_amount": doc.advance_amount,
            "employee": doc.employee,
            "status": doc.status
        }

        return send_response(200, "Success", "Employee Advance updated successfully.", employee_advance=advance_data)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Update Employee Advance API")
        return send_response(500, "Error", "Unable to update employee advance.")
