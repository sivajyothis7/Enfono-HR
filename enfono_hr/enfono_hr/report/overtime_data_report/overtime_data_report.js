// Copyright (c) 2025, siva and contributors
// For license information, please see license.txt


frappe.query_reports["Overtime Data Report"] = {
    "filters": [
        {
            "fieldname": "employee",
            "label": "Employee",
            "fieldtype": "Link",
            "options": "Employee",
            "reqd": 0
        },
        {
            "fieldname": "from_date",
            "label": "From Date",
            "fieldtype": "Date",
            "reqd": 0
        },
        {
            "fieldname": "to_date",
            "label": "To Date",
            "fieldtype": "Date",
            "reqd": 0
        }
    ],

    "onload": function(report) {
    },

   

    
};
