# Business Needed Solutions (BNS)

A comprehensive Frappe/ERPNext application that provides essential business solutions including document submission restrictions, internal transfer management, validation systems, and enhanced printing capabilities.

## 🚀 Features

### 1. **Unified Submission Restriction System**
- **Centralized Control**: Single setting to control submission restrictions across all document types
- **Document Categories**: Automatically categorizes documents into Stock, Transaction, and Order types
- **Role-based Overrides**: Configurable role permissions to bypass restrictions
- **Smart Validation**: Intelligent handling of stock updates vs. references

### 2. **Internal Transfer Management**
- **Inter-company Transfers**: Seamless creation of Purchase Receipts from Delivery Notes for internal customers
- **GST Validation**: Automatic GSTIN comparison for billing calculations
- **Status Management**: Automatic status updates for internal transfers
- **Address Handling**: Smart address swapping for internal transfers

### 3. **Enhanced Validation Systems**
- **PAN Uniqueness**: Ensures unique PAN numbers across Customers and Suppliers
- **Item Validation**: Validates expense account configuration for non-stock items
- **Stock Update Validation**: Ensures proper referencing when stock updates are disabled

### 4. **Advanced Printing System**
- **Configurable Formats**: Dynamic print format assignment from BNS Settings
- **Direct Printing**: One-click printing with keyboard shortcuts (Ctrl+P)
- **Sales Invoice Support**: Special handling for multiple invoice copies
- **Fallback Formats**: Automatic fallback to default formats

### 5. **Vehicle/Transporter Management**
- **e-Waybill Integration**: Update vehicle and transporter details for e-Waybill documents
- **Status Validation**: Ensures updates only when e-Waybill status allows
- **Flexible Updates**: Support for partial updates (vehicle, transporter, or both)

## 📁 Project Structure

```
business_needed_solutions/
├── business_needed_solutions/
│   ├── business_needed_solutions/
│   │   ├── overrides/                    # Document validation overrides
│   │   │   ├── submission_restriction.py # Unified submission restriction
│   │   │   ├── pan_validation.py        # PAN uniqueness validation
│   │   │   ├── item_validation.py       # Item expense account validation
│   │   │   └── stock_update_validation.py # Stock update validation
│   │   ├── doctype/                      # Custom DocTypes
│   │   │   ├── bns_settings/            # Main settings configuration
│   │   │   └── ...                      # Other custom DocTypes
│   │   ├── utils.py                     # Utility functions
│   │   └── __init__.py
│   ├── migration.py                     # Migration scripts
│   ├── update_vehicle.py               # Vehicle update functionality
│   ├── test_submission_restriction.py  # Test suite
│   └── hooks.py                        # App hooks and configurations
├── sites/assets/business_needed_solutions/js/
│   ├── direct_print.js                 # Direct printing system
│   ├── discount_manipulation_by_type.js # Discount handling
│   ├── sales_invoice_form.js           # Sales invoice enhancements
│   └── ...                             # Other JavaScript files
└── README.md                           # This file
```

## 🛠️ Installation

1. **Install the App**:
   ```bash
   bench get-app business_needed_solutions
   bench install-app business_needed_solutions
   ```

2. **Migrate the App**:
   ```bash
   bench migrate
   ```

3. **Setup BNS Settings**:
   - Navigate to **BNS Settings** in the desk
   - Configure your preferences for:
     - Submission restrictions
     - Print formats
     - Validation settings
     - Discount types

## ⚙️ Configuration

### BNS Settings Configuration

#### 1. **Submission Restrictions**
- **Enable/Disable**: Toggle submission restrictions globally
- **Override Roles**: Assign roles that can bypass restrictions
- **Document Categories**: Automatic categorization of documents

#### 2. **Print Formats**
- **Doctype Mapping**: Map document types to specific print formats
- **Fallback Formats**: Default formats when not configured
- **Dynamic Loading**: Automatic format loading from settings

#### 3. **Validation Settings**
- **PAN Uniqueness**: Enforce unique PAN across customers/suppliers
- **Expense Account**: Require expense accounts for non-stock items
- **Stock Updates**: Validate stock references when updates disabled

#### 4. **Discount Configuration**
- **Single/Triple Mode**: Switch between discount types
- **Field Visibility**: Automatic field showing/hiding
- **Property Setters**: Dynamic field property management

## 🔧 Usage

### Submission Restrictions

The system automatically restricts document submissions based on configured settings:

```python
# Example: Document submission will be restricted unless user has override role
# This is handled automatically by the system
```

### Internal Transfers

Create Purchase Receipts from Delivery Notes for internal customers:

```python
# Via UI: Use the "Create Purchase Receipt" button on Delivery Notes
# Via API: Call the make_bns_internal_purchase_receipt function
```

### Direct Printing

Print documents directly with keyboard shortcuts:

```javascript
// Ctrl+P (or Cmd+P on Mac) will trigger direct printing
// For Sales Invoices: Shows dropdown for invoice copy selection
// For other documents: Direct PDF generation and printing
```

### Vehicle Updates

Update vehicle and transporter details:

```python
# Via API: Call update_vehicle_or_transporter function
update_vehicle_or_transporter(
    doctype="Delivery Note",
    docname="DN-001",
    vehicle_no="MH12AB1234",
    transporter="Transporter Name"
)
```

## 🧪 Testing

Run the comprehensive test suite:

```python
# Execute the test script
python -c "from business_needed_solutions.test_submission_restriction import test_submission_restriction; test_submission_restriction()"
```

The test suite validates:
- BNS Settings configuration
- Document categorization
- Permission checking
- Legacy field cleanup

## 🔒 Security Features

- **Role-based Access**: Granular permission control
- **Validation Layers**: Multiple validation points for data integrity
- **Audit Trail**: Comprehensive logging of all operations
- **Error Handling**: Graceful error handling with user-friendly messages

## 📊 Logging

The app includes comprehensive logging for debugging and monitoring:

```python
import logging
logger = logging.getLogger(__name__)

# Log levels used:
# DEBUG: Detailed information for debugging
# INFO: General information about operations
# WARNING: Warning messages for potential issues
# ERROR: Error messages for failed operations
```

## 🔄 Migration

The app includes automatic migration scripts that handle:

- **Settings Migration**: Automatic migration of old settings to new unified system
- **Role Migration**: Transfer of override roles to new structure
- **Field Cleanup**: Removal of deprecated fields
- **Data Validation**: Verification of migrated data integrity

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with proper documentation
4. Add tests for new functionality
5. Submit a pull request

## 📝 Code Standards

- **Type Hints**: All Python functions include type annotations
- **Documentation**: Comprehensive docstrings for all functions
- **Error Handling**: Proper exception handling with custom exceptions
- **Logging**: Appropriate logging levels for debugging
- **Testing**: Unit tests for critical functionality

## 🐛 Troubleshooting

### Common Issues

1. **Print Formats Not Working**:
   - Check BNS Settings configuration
   - Verify print format exists
   - Check browser popup settings

2. **Submission Restrictions Not Working**:
   - Verify BNS Settings are saved
   - Check user roles and permissions
   - Review document categorization

3. **Internal Transfers Failing**:
   - Ensure internal customer/supplier setup
   - Verify company assignments
   - Check GSTIN configurations

### Debug Mode

Enable debug logging for troubleshooting:

```python
import logging
logging.getLogger('business_needed_solutions').setLevel(logging.DEBUG)
```

## 📄 License

This project is licensed under the MIT License - see the [license.txt](license.txt) file for details.

## 👥 Authors

- **Sagar Ratan Garg** - *Initial work* - [sagar1ratan1garg1@gmail.com](mailto:sagar1ratan1garg1@gmail.com)

## 🙏 Acknowledgments

- Frappe Framework team for the excellent platform
- ERPNext community for continuous improvements
- All contributors who have helped improve this application

---

**Note**: This application is designed for Frappe/ERPNext version 15.0 and above. Please ensure compatibility with your ERPNext version before installation.