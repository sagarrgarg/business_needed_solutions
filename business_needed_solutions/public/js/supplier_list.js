frappe.listview_settings['Supplier'] = frappe.listview_settings['Supplier'] || {};

var _originalOnload = frappe.listview_settings['Supplier'].onload;

frappe.listview_settings['Supplier'].onload = function (listview) {
  if (_originalOnload) _originalOnload(listview);

  frappe.db.get_single_value('BNS Settings', 'know_your_vendor_form')
    .then(function (url) {
      if (!url) return;
      listview.page.add_inner_button(__('Download KYV Form'), function () {
        window.open(url, '_blank');
      });
    });
};
