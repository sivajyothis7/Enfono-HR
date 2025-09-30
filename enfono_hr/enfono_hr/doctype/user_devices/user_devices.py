# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class UserDevices(Document):
    
    def after_insert(self):
        frappe.log_error(f"Device Token saved: {self.device_token}", "UserDevices")


