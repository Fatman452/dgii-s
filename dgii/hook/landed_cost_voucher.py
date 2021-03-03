import frappe
from frappe.utils import flt, add_days, nowdate
from erpnext.controllers.accounts_controller import get_taxes_and_charges

def on_submit(doc, method):
	if not doc.taxes:
		return

	for tax in doc.taxes:
		if tax.create_invoice:
			tax = tax.update({"company": doc.company})
			create_purchase_invoice(tax)

@frappe.whitelist()
def create_purchase_invoice(row):
	import json

	if type(row) == str:
		_row = frappe._dict(json.loads(row))
		row = frappe.get_doc("Landed Cost Taxes and Charges", _row.name)

	if row.invoice:
		return "This LCV already has an invoice"

	total  = abs(row.total)
	amount = abs(row.amount)
	p_inv = frappe.new_doc("Purchase Invoice")
	stock_uom = frappe.db.get_single_value("Stock Settings", "stock_uom")
	
	credit_to_dop, credit_to_usd = frappe.get_value(
		"Company",
		row.company, 
		[
			"default_payable_account",
			"default_payable_account_usd"
		]
	)
	credit_obj = {
		"DOP": credit_to_dop,
		"USD": credit_to_usd,
	}

	if not row.expense_account:
		frappe.throw("Please set and expense account")

	inv_date = row.date or nowdate()

	p_inv.update({
		"invoice_type": "Services",
		"supplier": row.supplier,
		"posting_date": inv_date,
		"date": inv_date,
		"bill_no": inv_date,
		"bill_date": inv_date,
		"supplier_invoice_no": row.supplier_invoice_no,
		"tipo_bienes_y_servicios_comprados": row.tipo_bienes_y_servicios_comprados,
		"company": frappe.db.get_value("Landed Cost Voucher", row.parent, "company"),
		"due_date": add_days(inv_date, 30),
		"update_stock": 0,
		"cost_center": row.cost_center,
		"credit_to": credit_obj[row.currency],
		"is_petty_cash": row.is_petty_cash,
		"set_posting_time": 1,
		"bill_no": row.supplier_invoice or "",
		"vencimiento_ncf": row.expiry_date or "",
		"taxes_and_charges": row.purchase_taxes_and_charges_template or "",
		"price_list": "Compra estándar {}".format(row.currency or "DOP"),
		"currency": row.currency or "DOP",
		"price_list_currency": row.currency or "DOP",
		"party_account_currency": row.currency or "DOP",
		"exchange_rate": row.exchange_rate or "1",
		"account": row.expense_account,
	})
	# Let's create the item if doesn't exists
	item_name = "Voucher Expenses" 

	p_inv.append("items", {
		"item_name": item_name,
		"qty": 1,
		"uom": stock_uom or "Unit",
		"conversion_factor": 1,
		"stock_uom": stock_uom or "Unit",
		"cost_center": row.cost_center,
		"stock_qty": 1,
		"expense_account": row.expense_account,
		"remarks": row.description,
		"rate": total if total else amount,
	})
	p_inv.set_missing_values()
	
	if row.purchase_taxes_and_charges_template and not row.tax_amount:
		frappe.throw("Favor especificar el monto del impuesto")

	if row.purchase_taxes_and_charges_template:
		for r in get_taxes_and_charges(master_doctype="Purchase Taxes and Charges Template", master_name=row.purchase_taxes_and_charges_template,):
			r.update({
				"charge_type": "Actual",
				"tax_amount": row.tax_amount
			})
			p_inv.append("taxes", r)
	

	p_inv.calculate_taxes_and_totals()
	p_inv.save()
	p_inv.submit()
	row.update({
		"invoice": p_inv.name,
		"date": p_inv.posting_date, 
		"create_invoice": 1 
		#if created using the button this needs to be set to 1
	})
	row.db_update()

	if row.amount < 0:
		pay_and_return(p_inv)

	return "Purchase Invoice {} Created".format(p_inv.name)

@frappe.whitelist()
def get_rate_from_template(template):
	return flt(frappe.db.sql("""
		SELECT 
			SUM(`tabPurchase Taxes and Charges`.rate) as rate
		FROM 
			`tabPurchase Taxes and Charges` 
		JOIN
			`tabPurchase Taxes and Charges Template`
		ON
			`tabPurchase Taxes and Charges`.parent = `tabPurchase Taxes and Charges Template`.name
		WHERE
			`tabPurchase Taxes and Charges`.parent = %s
	""", template)[0][0])