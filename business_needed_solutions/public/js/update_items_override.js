frappe.provide("business_needed_solutions.updateItems");

business_needed_solutions.updateItems = (() => {
  const DOCTYPES = ["Sales Order", "Purchase Order"];
  let settingsCache = null;
  let settingsPromise = null;

  const getChildMeta = (doctype) => frappe.get_meta(`${doctype} Item`);
  const getPrecision = (childMeta, fieldname) =>
    (childMeta?.fields || []).find((f) => f.fieldname === fieldname)?.precision;
  const asFloat = (v) => flt(v || 0);

  const computeRate = (frm, discountType, row) => {
    const plr = asFloat(row.price_list_rate);
    if (discountType === "Single") {
      const disc = asFloat(row.discount_percentage);
      return plr * (1 - disc / 100);
    }

    if (frm.doc.doctype === "Sales Order") {
      const d1 = asFloat(row.custom_d1_);
      const d2 = asFloat(row.custom_d2_);
      const d3 = asFloat(row.custom_d3_);
      let rate = plr;
      [d1, d2, d3].forEach((d) => {
        rate *= 1 - d / 100;
      });
      return rate;
    }

    // Purchase Order in Triple mode: no triple discount fields exist, treat as no discount
    return plr;
  };

  const updateComputedFields = (frm, discountType, row) => {
    row.amount = asFloat(row.qty) * computeRate(frm, discountType, row);
  };

  const getItemQueryFilters = (frm) => {
    // Mirrors ERPNext's Update Items dialog item filters
    if (frm.doc.doctype === "Sales Order") {
      return { is_sales_item: 1 };
    }

    // Purchase Order
    if (frm.doc.is_subcontracted) {
      if (frm.doc.is_old_subcontracting_flow) {
        return { is_sub_contracted_item: 1 };
      }
      return { is_stock_item: 0 };
    }

    return { is_purchase_item: 1 };
  };

  const getBnsSettings = async () => {
    if (settingsCache) return settingsCache;
    if (!settingsPromise) {
      settingsPromise = frappe.db
        .get_doc("BNS Settings")
        .then((doc) => {
          settingsCache = doc || {};
          return settingsCache;
        })
        .catch(() => {
          settingsCache = {};
          return settingsCache;
        });
    }
    return settingsPromise;
  };

  const isEnabled = async () => {
    const s = await getBnsSettings();
    return cint(s.enable_custom_update_items_po_so) === 1;
  };

  const getDiscountType = async () => {
    const s = await getBnsSettings();
    return s.discount_type || "Single";
  };

  const shouldShowButton = (frm) => {
    if (frm.doc.docstatus !== 1) return false;
    if (!frm.has_perm("write")) return false;

    if (frm.doc.doctype === "Sales Order") {
      return (
        frm.doc.status !== "Closed" &&
        flt(frm.doc.per_delivered) < 100 &&
        flt(frm.doc.per_billed) < 100
      );
    }

    if (frm.doc.doctype === "Purchase Order") {
      const canUpdateItems = !frm.doc.__onload || frm.doc.__onload.can_update_items;
      return (
        canUpdateItems &&
        !["Closed", "Delivered"].includes(frm.doc.status) &&
        flt(frm.doc.per_received) < 100 &&
        flt(frm.doc.per_billed) < 100
      );
    }

    return false;
  };

  const getAllowedUoms = async (itemCode) => {
    if (!itemCode) return [];
    
    try {
      const item = await frappe.db.get_doc("Item", itemCode);
      const allowed = [];
      if (item.stock_uom) allowed.push(item.stock_uom);
      (item.uoms || []).forEach((d) => {
        if (d.uom && !allowed.includes(d.uom)) allowed.push(d.uom);
      });
      return allowed;
    } catch (e) {
      return [];
    }
  };

  const applyItemDetailsToDialogRow = (frm, dialog, rowDoc, discountType) => {
    if (!rowDoc?.item_code) return;

    // Fetch item details to fill Price List Rate / UOM / Conversion Factor
    frappe.call({
      method: "erpnext.stock.get_item_details.get_item_details",
      args: {
        doc: frm.doc,
        args: {
          item_code: rowDoc.item_code,
          set_warehouse: frm.doc.set_warehouse,
          customer: frm.doc.customer || frm.doc.party_name,
          quotation_to: frm.doc.quotation_to,
          supplier: frm.doc.supplier,
          currency: frm.doc.currency,
          is_internal_supplier: frm.doc.is_internal_supplier,
          is_internal_customer: frm.doc.is_internal_customer,
          conversion_rate: frm.doc.conversion_rate,
          price_list: frm.doc.selling_price_list || frm.doc.buying_price_list,
          price_list_currency: frm.doc.price_list_currency,
          plc_conversion_rate: frm.doc.plc_conversion_rate,
          company: frm.doc.company,
          order_type: frm.doc.order_type,
          is_pos: cint(frm.doc.is_pos),
          is_return: cint(frm.doc.is_return),
          is_subcontracted: frm.doc.is_subcontracted,
          ignore_pricing_rule: frm.doc.ignore_pricing_rule,
          doctype: frm.doc.doctype,
          name: frm.doc.name,
          qty: rowDoc.qty || 1,
          uom: rowDoc.uom,
          pos_profile: cint(frm.doc.is_pos) ? frm.doc.pos_profile : "",
          tax_category: frm.doc.tax_category,
          child_doctype: frm.doc.doctype + " Item",
          is_old_subcontracting_flow: frm.doc.is_old_subcontracting_flow,
        },
      },
      callback: (r) => {
        if (r.exc) {
          console.error("Error fetching item details:", r.exc);
          return;
        }
        
        if (!r.message) {
          console.warn("No item details returned for item:", rowDoc.item_code);
          return;
        }

        const {
          qty,
          item_name,
          price_list_rate,
          uom,
          conversion_factor,
          stock_uom,
        } = r.message;

        // Update dialog row
        const target = dialog.fields_dict.trans_items.df.data.find(
          (d) => d.idx === rowDoc.idx
        );

        if (!target) {
          console.warn("Target row not found for idx:", rowDoc.idx);
          return;
        }

        // Update fields - always refresh from server response when item_code changes
        if (stock_uom) target.stock_uom = stock_uom;
        if (uom) target.uom = uom;
        if (conversion_factor) target.conversion_factor = conversion_factor;
        if (qty && !target.qty) target.qty = qty;
        if (price_list_rate !== undefined && price_list_rate !== null) {
          target.price_list_rate = price_list_rate;
        }
        if (item_name) target.item_name = item_name;

        updateComputedFields(frm, discountType, target);
        dialog.fields_dict.trans_items.grid.refresh();
      },
    });

    // Fetch Stock UOM / Item Name if not returned by get_item_details
    if (!rowDoc.stock_uom || !rowDoc.item_name) {
      frappe.db.get_value("Item", rowDoc.item_code, ["stock_uom", "item_name"]).then((r) => {
        const stockUom = r?.message?.stock_uom;
        const itemName = r?.message?.item_name;
        const target = dialog.fields_dict.trans_items.df.data.find(
          (d) => d.idx === rowDoc.idx
        );
        if (!target) return;

        if (!target.stock_uom && stockUom) {
          target.stock_uom = stockUom;
          if (!target.uom) target.uom = stockUom;
        }
        if (!target.item_name && itemName) {
          target.item_name = itemName;
        }

        updateComputedFields(frm, discountType, target);
        dialog.fields_dict.trans_items.grid.refresh();
      });
    }
  };

  const buildDialogFields = async (frm, childMeta, getDialog) => {
    const discountType = await getDiscountType();
    const dateFieldname = frm.doc.doctype === "Sales Order" ? "delivery_date" : "schedule_date";
    const dateLabel = frm.doc.doctype === "Sales Order" ? __("Delivery Date") : __("Reqd by date");

    const fields = [
      {
        fieldtype: "Data",
        fieldname: "docname",
        read_only: 1,
        hidden: 1,
      },
      {
        fieldtype: "Data",
        fieldname: "item_name",
        read_only: 1,
        hidden: 1,
      },
      {
        fieldtype: "Data",
        fieldname: "original_item_code",
        read_only: 1,
        hidden: 1,
      },
      {
        fieldtype: "Data",
        fieldname: "original_item_name",
        read_only: 1,
        hidden: 1,
      },
      // --- Row edit fields (basic editable fields; conversion factor not editable) ---
      {
        fieldtype: "Link",
        fieldname: "item_code",
        options: "Item",
        in_list_view: 1,
        columns: 2,
        label: __("Item"),
        reqd: 1,
        get_query: () => ({
          query: "erpnext.controllers.queries.item_query",
          filters: getItemQueryFilters(frm),
        }),
        formatter: (value, df, options, doc) => {
          if (!value) return "";
          const namePart = doc && doc.item_name ? `:${doc.item_name}` : "";
          return `${value}${namePart}`;
        },
        onchange: async function () {
          const dialog = getDialog && getDialog();
          if (!dialog || !this.value) return;

          // Get discountType for this call
          const currentDiscountType = await getDiscountType();
          
          // Update item_code in doc
          this.doc.item_code = this.value;
          
          // Allow item_code changes on existing rows - validation happens server-side
          applyItemDetailsToDialogRow(frm, dialog, this.doc, currentDiscountType);
        },
      },
      {
        fieldtype: "Date",
        fieldname: dateFieldname,
        in_list_view: 0,
        label: dateLabel,
        reqd: 1,
      },
      {
        fieldtype: "Link",
        fieldname: "stock_uom",
        options: "UOM",
        in_list_view: 0,
        label: __("Stock UOM"),
        read_only: 1,
      },
      {
        fieldtype: "Float",
        fieldname: "conversion_factor",
        in_list_view: 0,
        label: __("Conversion Factor"),
        precision: getPrecision(childMeta, "conversion_factor"),
        read_only: 1,
      },
      // --- List view columns (as requested) ---
      {
        fieldtype: "Float",
        fieldname: "qty",
        in_list_view: 1,
        columns: 1,
        label: __("Qty"),
        precision: getPrecision(childMeta, "qty"),
        onchange: function () {
          updateComputedFields(frm, discountType, this.doc);
          const dialog = getDialog && getDialog();
          if (dialog) dialog.fields_dict.trans_items.grid.refresh();
        },
      },
      {
        fieldtype: "Link",
        fieldname: "uom",
        options: "UOM",
        in_list_view: 1,
        columns: 1,
        label: __("UOM"),
        reqd: 1,
        get_query: async function () {
          const allowed = await getAllowedUoms(this.doc.item_code);
          return { filters: { name: ["in", allowed.length ? allowed : [""] ] } };
        },
        onchange: async function () {
          const dialog = getDialog && getDialog();
          if (!dialog || !this.doc.item_code) return;
          
          const rowDocname = this.doc.docname;
          const currentDiscountType = await getDiscountType();
          
          // Fetch both conversion_factor and price_list_rate for the new UOM
          frappe.call({
            method: "erpnext.stock.get_item_details.get_item_details",
            args: {
              doc: frm.doc,
              args: {
                item_code: this.doc.item_code,
                set_warehouse: frm.doc.set_warehouse,
                customer: frm.doc.customer || frm.doc.party_name,
                quotation_to: frm.doc.quotation_to,
                supplier: frm.doc.supplier,
                currency: frm.doc.currency,
                is_internal_supplier: frm.doc.is_internal_supplier,
                is_internal_customer: frm.doc.is_internal_customer,
                conversion_rate: frm.doc.conversion_rate,
                price_list: frm.doc.selling_price_list || frm.doc.buying_price_list,
                price_list_currency: frm.doc.price_list_currency,
                plc_conversion_rate: frm.doc.plc_conversion_rate,
                company: frm.doc.company,
                order_type: frm.doc.order_type,
                is_pos: cint(frm.doc.is_pos),
                is_return: cint(frm.doc.is_return),
                is_subcontracted: frm.doc.is_subcontracted,
                ignore_pricing_rule: frm.doc.ignore_pricing_rule,
                doctype: frm.doc.doctype,
                name: frm.doc.name,
                qty: this.doc.qty || 1,
                uom: this.value, // New UOM
                pos_profile: cint(frm.doc.is_pos) ? frm.doc.pos_profile : "",
                tax_category: frm.doc.tax_category,
                child_doctype: frm.doc.doctype + " Item",
                is_old_subcontracting_flow: frm.doc.is_old_subcontracting_flow,
              },
            },
            callback: (r) => {
              if (r.exc || !r.message) return;
              
              const { conversion_factor, price_list_rate } = r.message;
              
              dialog.fields_dict.trans_items.df.data.some((d) => {
                if (d.docname === rowDocname) {
                  if (conversion_factor) {
                    d.conversion_factor = conversion_factor;
                  }
                  // Update price_list_rate for the new UOM
                  if (price_list_rate !== undefined && price_list_rate !== null) {
                    d.price_list_rate = price_list_rate;
                  }
                  updateComputedFields(frm, currentDiscountType, d);
                  dialog.fields_dict.trans_items.grid.refresh();
                  return true;
                }
              });
            },
          });
        },
      },
      {
        fieldtype: "Currency",
        fieldname: "price_list_rate",
        options: "currency",
        in_list_view: 1,
        columns: 1,
        label: __("Price List Rate"),
        precision: getPrecision(childMeta, "price_list_rate"),
        onchange: function () {
          updateComputedFields(frm, discountType, this.doc);
          const dialog = getDialog && getDialog();
          if (dialog) dialog.fields_dict.trans_items.grid.refresh();
        },
      },
    ];

    // Discount fields
    if (discountType === "Single") {
      fields.push({
        fieldtype: "Percent",
        fieldname: "discount_percentage",
        in_list_view: 1,
        columns: 1,
        label: __("Discount"),
        precision: getPrecision(childMeta, "discount_percentage"),
        onchange: function () {
          updateComputedFields(frm, discountType, this.doc);
          const dialog = getDialog && getDialog();
          if (dialog) dialog.fields_dict.trans_items.grid.refresh();
        },
      });
    } else if (frm.doc.doctype === "Sales Order") {
      fields.push(
        {
          fieldtype: "Percent",
          fieldname: "custom_d1_",
          in_list_view: 1,
          columns: 1,
          label: __("D1"),
          precision: getPrecision(childMeta, "custom_d1_"),
          onchange: function () {
            const d1 = asFloat(this.doc.custom_d1_);
            if (!d1) {
              this.doc.custom_d2_ = 0;
              this.doc.custom_d3_ = 0;
            }
            updateComputedFields(frm, discountType, this.doc);
            const dialog = getDialog && getDialog();
            if (dialog) dialog.fields_dict.trans_items.grid.refresh();
          },
        },
        {
          fieldtype: "Percent",
          fieldname: "custom_d2_",
          in_list_view: 1,
          columns: 1,
          label: __("D2"),
          precision: getPrecision(childMeta, "custom_d2_"),
          onchange: function () {
            const d2 = asFloat(this.doc.custom_d2_);
            if (!d2) {
              this.doc.custom_d3_ = 0;
            }
            updateComputedFields(frm, discountType, this.doc);
            const dialog = getDialog && getDialog();
            if (dialog) dialog.fields_dict.trans_items.grid.refresh();
          },
        },
        {
          fieldtype: "Percent",
          fieldname: "custom_d3_",
          in_list_view: 1,
          columns: 1,
          label: __("D3"),
          precision: getPrecision(childMeta, "custom_d3_"),
          onchange: function () {
            updateComputedFields(frm, discountType, this.doc);
            const dialog = getDialog && getDialog();
            if (dialog) dialog.fields_dict.trans_items.grid.refresh();
          },
        }
      );
    }

    // Amount (display only)
    fields.push({
      fieldtype: "Currency",
      fieldname: "amount",
      options: "currency",
      in_list_view: 1,
      columns: 1,
      label: __("Amount"),
      read_only: 1,
    });

    // Keep ERPNext subcontracting PO support (only when needed)
    if (
      frm.doc.doctype === "Purchase Order" &&
      frm.doc.is_subcontracted &&
      !frm.doc.is_old_subcontracting_flow
    ) {
      fields.push(
        {
          fieldtype: "Link",
          fieldname: "fg_item",
          options: "Item",
          in_list_view: 0,
          label: __("Finished Good Item"),
          get_query: () => ({
            filters: {
              is_stock_item: 1,
              is_sub_contracted_item: 1,
              default_bom: ["!=", ""],
            },
          }),
        },
        {
          fieldtype: "Float",
          fieldname: "fg_item_qty",
          in_list_view: 0,
          label: __("Finished Good Item Qty"),
          precision: getPrecision(childMeta, "fg_item_qty"),
        }
      );
    }

    return fields;
  };

  const getInitialData = async (frm) => {
    const discountType = await getDiscountType();
    const dateFieldname = frm.doc.doctype === "Sales Order" ? "delivery_date" : "schedule_date";

    return (frm.doc.items || []).map((d) => {
      const row = {
        docname: d.name,
        item_code: d.item_code,
        item_name: d.item_name,
        original_item_code: d.item_code,
        original_item_name: d.item_name,
        [dateFieldname]: d[dateFieldname],
        uom: d.uom,
        stock_uom: d.stock_uom,
        conversion_factor: d.conversion_factor,
        qty: d.qty,
        price_list_rate: d.price_list_rate,
        amount: 0,
      };

      if (discountType === "Single") {
        row.discount_percentage = d.discount_percentage;
      } else if (frm.doc.doctype === "Sales Order") {
        row.custom_d1_ = d.custom_d1_;
        row.custom_d2_ = d.custom_d2_;
        row.custom_d3_ = d.custom_d3_;
      }

      if (
        frm.doc.doctype === "Purchase Order" &&
        frm.doc.is_subcontracted &&
        !frm.doc.is_old_subcontracting_flow
      ) {
        row.fg_item = d.fg_item;
        row.fg_item_qty = d.fg_item_qty;
      }

      updateComputedFields(frm, discountType, row);
      return row;
    });
  };

  const openDialog = async (frm) => {
    const childMeta = getChildMeta(frm.doc.doctype);
    let dialog = null;
    const fields = await buildDialogFields(frm, childMeta, () => dialog);
    const data = await getInitialData(frm);

    const hasReservedStock =
      frm.doc.doctype === "Sales Order" && frm.doc.__onload && frm.doc.__onload.has_reserved_stock;

    dialog = new frappe.ui.Dialog({
      title: __("Update Items"),
      size: "extra-large",
      fields: [
        {
          fieldname: "trans_items",
          fieldtype: "Table",
          label: __("Items"),
          cannot_add_rows: false,
          in_place_edit: false,
          reqd: 1,
          data,
          get_data: () => data,
          fields,
        },
      ],
      primary_action_label: __("Update"),
      primary_action: function () {
        const runUpdate = () => {
          const transItems = (this.get_values()?.trans_items || []).filter((d) => !!d.item_code);
          frappe.call({
            method:
              "business_needed_solutions.business_needed_solutions.overrides.update_items.update_child_items",
            freeze: true,
            args: {
              parent_doctype: frm.doc.doctype,
              parent_doctype_name: frm.doc.name,
              child_docname: "items",
              trans_items: transItems,
            },
            callback: () => frm.reload_doc(),
          });
          this.hide();
        };

        if (hasReservedStock) {
          this.hide();
          frappe.confirm(
            __(
              "The reserved stock will be released when you update items. Are you certain you wish to proceed?"
            ),
            () => runUpdate()
          );
        } else {
          runUpdate();
        }
      },
    });

    dialog.show();
  };

  const refresh = async (frm) => {
    if (!DOCTYPES.includes(frm.doc.doctype)) return;
    if (!(await isEnabled())) return;

    // Ensure ERPNext's button (added by core scripts) doesn't show.
    // Use a short delay to be robust against handler ordering, then re-add BNS button.
    setTimeout(() => {
      frm.remove_custom_button(__("Update Items"));
      if (shouldShowButton(frm)) {
        frm.add_custom_button(__("Update Items"), () => openDialog(frm));
      }
    }, 0);
  };

  return { refresh };
})();

["Sales Order", "Purchase Order"].forEach((dt) => {
  frappe.ui.form.on(dt, {
    refresh(frm) {
      business_needed_solutions.updateItems.refresh(frm);
    },
  });
});

