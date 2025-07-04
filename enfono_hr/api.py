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
            leave_approver_name=get_user_full_name(leave_approver)
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

    frappe.local.response.update({
        "status_code": 200,
        "status_message": "Success",
        "latest_android_version": getattr(doc, "latest_android_version", None),
        "latest_ios_version": getattr(doc, "latest_ios_version", None),
        "android_link": getattr(doc, "android_link", None),
        "ios_link": getattr(doc, "ios_link", None)
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
            return send_response(401, "Unauthorized", "Please login first.")

        employee = frappe.db.get_value("Employee", {"user_id": user})

        filters = {
            "approver": user,
        }

        if employee:
            filters["employee"] = ["!=", employee]

        raw_requests = frappe.get_all(
            "Shift Request",
            filters=filters,
            fields=["name", "employee", "shift_type", "from_date", "to_date", "status", "creation"],
            order_by="creation desc"
        )

        shift_requests = []
        for req in raw_requests:
            req["employee_name"] = frappe.db.get_value("Employee", req["employee"], "employee_name")
            shift_requests.append(req)

        return send_response(
            200,
            "Success",
            "Pending shift requests fetched.",
            shift_requests=shift_requests
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get Team Shift Requests Failed")
        return send_response(500, "Error", "Something went wrong.")


#####Approve_or_reject_shift_request#####

@frappe.whitelist()
def approve_or_reject_shift_request(name, action):
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

        if action not in ["Approved", "Rejected"]:
            return send_response(400, "Invalid Action", "Only 'Approved' or 'Rejected' actions are allowed.")

        doc = frappe.get_doc("Shift Request", name)

        employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
        if user == employee_user:
            return send_response(403, "Forbidden", "You cannot approve your own request.")

        if doc.approver != user:
            return send_response(403, "Forbidden", "You are not authorized to approve this request.")

        doc.status = action
        doc.save()

        if doc.docstatus == 0:
            doc.submit()

        return send_response(200, "Success", f"Shift request {action.lower()} successfully.", request_id=doc.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Shift Request Approval Failed")
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
            "status": "Open",
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
            fields=["name", "leave_type", "from_date", "to_date", "status", "creation", "leave_approver"],
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
                "status": app.status,
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

        current_employee = frappe.db.get_value("Employee", {"user_id": user})
        employees = frappe.get_all("Employee", filters={"leave_approver": user}, pluck="name")

        if not employees:
            return send_response(200, "Success", "No team members found.", team_requests=[])

        if current_employee and current_employee in employees:
            employees.remove(current_employee)

        if not employees:
            return send_response(200, "Success", "No team leave requests found.", team_requests=[])

        leave_apps_raw = frappe.get_all(
            "Leave Application",
            filters={"employee": ["in", employees]},
            fields=["name", "employee", "leave_type", "from_date", "to_date", "status", "creation"],
            order_by="creation desc"
        )

        leave_apps = []
        for app in leave_apps_raw:
            employee_name = frappe.db.get_value("Employee", app["employee"], "employee_name")
            app["employee_name"] = employee_name
            leave_apps.append(app)

        return send_response(200, "Success", "Team leave applications fetched.", leave_applications=leave_apps)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Team Leave Applications Failed")
        return send_response(500, "Error", "Something went wrong.")



######Approve Leave Requests List#####



@frappe.whitelist()
def approve_or_reject_leave_application(application_id, action):
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

        if action not in ["Approved", "Rejected"]:
            return send_response(400, "Invalid Action", "Action must be 'Approved' or 'Rejected'.")

        doc = frappe.get_doc("Leave Application", application_id)

        employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
        if employee_user == user:
            return send_response(403, "Forbidden", "You can't approve your own request.")

        if doc.leave_approver != user:
            return send_response(403, "Forbidden", "You are not the assigned approver.")

        doc.status = action
        doc.save()
        if doc.docstatus == 0:
            doc.submit()

        return send_response(200, "Success", f"Leave application {action.lower()} successfully.", application_id=doc.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Leave Approval Failed")
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
    email=None,
    phone=None,
    mobile_no=None,
    whatsapp_no=None,
    website=None,
    designation=None,
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
            "lead_owner": user,
            "email_id": email,
            "phone": phone,
            "mobile_no": mobile_no,
            "whatsapp_no": whatsapp_no,
            "website": website,
            "designation": designation,
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


#####View My Leads#####

@frappe.whitelist()
def get_my_leads():
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
            return send_response(401, "Unauthorized", "Please log in first.")

        leads = frappe.get_all(
            "Lead",
            filters={"owner": user},
            fields=[
                "name", "first_name", "company_name", "status", "request_type",
                "email_id", "phone", "mobile_no", "whatsapp_no", "city", "state",
                "country", "creation"
            ],
            order_by="creation desc"
        )

        return send_response(
            200,
            "Success",
            "Your leads fetched.",
            leads=leads
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Get My Leads Failed")
        return send_response(500, "Error", "Could not retrieve leads.")


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
        if lead.lead_owner != user:
            return send_response(403, "Forbidden", "You do not have permission to modify this lead.")

        editable_fields = [
            "first_name", "company_name", "status", "email_id", "phone",
            "mobile_no", "whatsapp_no", "website", "designation", "gender",
            "request_type", "city", "state", "country"
        ]

        valid_status = ["Lead", "Open", "Replied", "Interested", "Converted", "Do Not Contact"]
        valid_gender = ["Male", "Female", "Other"]
        valid_request_type = ["Product Enquiry", "Request for Information", "Suggestions", "Other"]

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
