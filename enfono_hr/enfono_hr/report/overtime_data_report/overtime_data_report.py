# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

def execute(filters=None):
    if not filters:
        filters = {}

    columns = [
        {"label": "Employee ID", "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 250},
        {"label": "Employee Name", "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
        {"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 120},
        {"label": "OT Hours", "fieldname": "ot_hours", "fieldtype": "Float", "width": 150},
        {"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150},
        {"label": "Overtime Status", "fieldname": "overtime_status", "fieldtype": "Data", "width": 170},
        {"label": "OT Amount", "fieldname": "ot_amount", "fieldtype": "Currency", "width": 170},
    ]

    conditions = []
    if filters.get("employee"):
        conditions.append(["employee", "=", filters["employee"]])
    if filters.get("from_date"):
        conditions.append(["date", ">=", filters["from_date"]])
    if filters.get("to_date"):
        conditions.append(["date", "<=", filters["to_date"]])

    data = frappe.get_list(
        "Overtime Data", 
        fields=["employee", "date", "ot_hours", "company", "overtime_status", "ot_amount"],
        filters=conditions,
        order_by="date asc",
        limit_page_length=1000
    )

    employee_ids = list(set([d["employee"] for d in data]))
    employee_map = frappe.get_all(
        "Employee",
        filters=[["name", "in", employee_ids]],
        fields=["name", "employee_name"]
    )
    emp_dict = {e["name"]: e["employee_name"] for e in employee_map}

    for d in data:
        d["employee_name"] = emp_dict.get(d["employee"], "")

    total_ot_hours = sum(flt(d.get("ot_hours", 0)) for d in data)
    total_ot_amount = sum(flt(d.get("ot_amount", 0)) for d in data)

    return columns, data
