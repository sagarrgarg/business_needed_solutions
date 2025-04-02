from erpnext.controllers.accounts_controller import AccountsController

# Override function with no-op logic (or logic of your choice)
def custom_disable_tax_included_prices(self):
    # Do nothing — keep included_in_print_rate as it is
    pass

# Monkey patch the method
AccountsController.disable_tax_included_prices_for_internal_transfer = custom_disable_tax_included_prices
