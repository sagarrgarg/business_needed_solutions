frappe.listview_settings['Purchase Receipt'] = {
    get_indicator: function(doc) {
        if (doc.status === "BNS Internally Transferred") {
            return [__("BNS Internally Transferred"), "purple", "status,=,BNS Internally Transferred"];
        } else if (doc.status === "Draft") {
            return [__("Draft"), "red", "status,=,Draft"];
        } else if (doc.status === "To Bill") {
            return [__("To Bill"), "orange", "status,=,To Bill"];
        } else if (doc.status === "Completed") {
            return [__("Completed"), "green", "status,=,Completed"];
        } else if (doc.status === "Return Issued") {
            return [__("Return Issued"), "grey", "status,=,Return Issued"];
        } else if (doc.status === "Cancelled") {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        } else if (doc.status === "Closed") {
            return [__("Closed"), "green", "status,=,Closed"];
        }
    }
}; 