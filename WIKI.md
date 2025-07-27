# Business Needed Solutions (BNS) - Complete User Guide

## 📚 **Table of Contents**

1. [Getting Started](#getting-started)
2. [BNS Settings Configuration](#bns-settings-configuration)
3. [Print Format Setup](#print-format-setup)
4. [Document Submission Control](#document-submission-control)
5. [Internal Transfer Management](#internal-transfer-management)
6. [Reports and Analytics](#reports-and-analytics)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## 🚀 **Getting Started**

### **Step 1: Installation**
1. **Install the App**: Your system administrator will install the BNS app
2. **Run Migration**: The system will automatically run necessary migrations
3. **Access BNS Settings**: Navigate to **BNS Settings** in your ERPNext desk

### **Step 2: Initial Setup**
1. **Open BNS Settings**: Go to **Setup > BNS Settings**
2. **Configure Basic Settings**: Set up your business preferences
3. **Save Settings**: Click **Save** to apply your configuration

### **Step 3: Verify Installation**
1. **Check Features**: Verify that BNS features are available
2. **Test Print Formats**: Try printing a document to test formats
3. **Verify Permissions**: Ensure your user has appropriate permissions

---

## ⚙️ **BNS Settings Configuration**

### **General Settings Tab**

#### **Discount Type Configuration**
- **Single Discount**: Standard single discount percentage
  - Use for simple discount structures
  - Shows single discount field in documents
  - Recommended for most businesses

- **Triple Compounded**: Advanced triple discount system
  - Use for complex discount structures
  - Shows three separate discount fields (D1, D2, D3)
  - Calculates compounded discounts automatically

#### **Validation Settings**
- **Enforce PAN Uniqueness**: 
  - ✅ **Enable**: Ensures unique PAN across customers/suppliers
  - ❌ **Disable**: Allows duplicate PAN numbers
  - **Recommendation**: Enable for compliance

- **Enforce Stock Update or Reference**:
  - ✅ **Enable**: Requires stock references when updates disabled
  - ❌ **Disable**: Allows stock documents without references
  - **Recommendation**: Enable for data integrity

- **Enforce Expense Account for Non-Stock Items**:
  - ✅ **Enable**: Requires expense accounts for non-stock items
  - ❌ **Disable**: Allows non-stock items without expense accounts
  - **Recommendation**: Enable for proper accounting

### **Submission Control Tab**

#### **Document Submission Restrictions**
- **Restrict Document Submission**:
  - ✅ **Enable**: Restricts document submissions to authorized users
  - ❌ **Disable**: Allows all users to submit documents
  - **Use Case**: Enable for approval workflows

#### **Override Roles Configuration**
1. **Add Override Roles**:
   - Click **Add Row** in the Override Roles table
   - Select roles that can bypass restrictions
   - Common roles: **System Manager**, **Accounts Manager**

2. **Role Permissions**:
   - **System Manager**: Always has override permissions
   - **Custom Roles**: Add specific roles for your organization
   - **Department Heads**: Consider adding department-specific roles

### **Print Options Tab**

#### **Rate Display Configuration**
- **Rate (Incl Tax)**:
  - ✅ **Enable**: Shows rates including tax
  - ❌ **Disable**: Hides inclusive tax rates
  - **Use Case**: Enable for customer-facing documents

- **Rate (Excl Tax)**:
  - ✅ **Enable**: Shows rates excluding tax
  - ❌ **Disable**: Hides exclusive tax rates
  - **Use Case**: Enable for internal documents

- **Secondary Rate Display**:
  - ✅ **Enable**: Shows additional rate information
  - ❌ **Disable**: Shows only primary rates
  - **Options**: Print UOM, Weight UOM

#### **Print Format Mapping**
1. **Add Print Format Mappings**:
   - Click **Add Row** in the Print Format table
   - **Doctype Map**: Select document type (e.g., Sales Invoice)
   - **Print Format**: Select the format to use

2. **Common Mappings**:
   - **Sales Invoice** → **BNS SI Dynamic V1**
   - **Delivery Note** → **BNS DN Dynamic V1**
   - **Purchase Order** → **BNS PO Dynamic V1**
   - **Sales Order** → **BNS SO Dynamic V1**

---

## 🖨️ **Print Format Setup**

### **Company Logo Configuration**

#### **Step 1: Prepare Your Logo**
- **Format**: PNG, JPG, or GIF
- **Size**: 200x200 pixels (recommended)
- **Quality**: High resolution for professional appearance
- **Background**: Transparent or white background

#### **Step 2: Upload Logo**
1. **Go to Company Settings**:
   - Navigate to **Setup > Company**
   - Select your company

2. **Upload Logo**:
   - Find the **Logo for Printing** field
   - Click **Attach** or **Choose File**
   - Select your logo file
   - Click **Upload**

3. **Verify Display**:
   - Print any document to verify logo appears
   - Logo will appear in the top-left corner

### **Bank Details Configuration**

#### **Step 1: Create Bank Account**
1. **Navigate to Chart of Accounts**:
   - Go to **Accounting > Chart of Accounts**
   - Find or create your bank account

2. **Configure Bank Details**:
   - **Account Name**: Your account name
   - **Bank**: Bank name
   - **Account Number**: Your account number
   - **Branch Code (IFSC)**: IFSC code for Indian banks
   - **IBAN**: For international accounts

#### **Step 2: Set Default Account**
1. **Mark as Default**:
   - In the bank account, check **Is Default**
   - This account will appear on all invoices

2. **Verify Configuration**:
   - Print an invoice to verify bank details
   - Details appear in the bottom section

### **Print Format Features**

#### **Sales Invoice Format (BNS SI Dynamic V1)**
**Features Available**:
- ✅ Company logo and branding
- ✅ Bank account details
- ✅ GST summary tables
- ✅ e-Invoice QR codes
- ✅ Multiple copy support
- ✅ Payment terms display
- ✅ Vehicle and transporter details
- ✅ Professional layout

**Configuration Options**:
- **Rate Display**: Inclusive/Exclusive tax rates
- **Discount Display**: Single or triple discount
- **Copy Types**: Original, Duplicate, Triplicate
- **GST Summary**: Automatic GST calculation and display

#### **Delivery Note Format (BNS DN Dynamic V1)**
**Features Available**:
- ✅ Vehicle and transporter details
- ✅ e-Waybill integration
- ✅ Shipping and dispatch information
- ✅ Terms of delivery
- ✅ Professional layout
- ✅ Company branding

**Configuration Options**:
- **Vehicle Details**: Automatic vehicle information
- **Transporter Details**: Transporter name and GST ID
- **Shipping Information**: Complete shipping details
- **Terms**: Custom terms of delivery

#### **Purchase Order Format (BNS PO Dynamic V1)**
**Features Available**:
- ✅ Supplier information
- ✅ Delivery terms
- ✅ Payment terms
- ✅ Professional branding
- ✅ Company details

**Configuration Options**:
- **Supplier Details**: Complete supplier information
- **Delivery Terms**: Custom delivery terms
- **Payment Terms**: Payment schedule and terms
- **Professional Layout**: Clean, professional appearance

### **Advanced Print Features**

#### **Rate Display Options**
1. **Inclusive Tax Rates**:
   - Shows rates including GST
   - Useful for customer-facing documents
   - Automatic tax calculation

2. **Exclusive Tax Rates**:
   - Shows rates excluding GST
   - Useful for internal documents
   - Clear base price display

3. **Secondary Rate Display**:
   - **Print UOM**: Shows rates in different units
   - **Weight UOM**: Shows rates per kilogram
   - Useful for manufacturing businesses

#### **Discount Management**
1. **Single Discount Mode**:
   - Simple percentage discount
   - Easy to understand and use
   - Standard business practice

2. **Triple Compounded Mode**:
   - Three separate discount fields
   - Automatic compounded calculation
   - Advanced discount structures

#### **Document Copy Support**
1. **Multiple Copies**:
   - Generate different invoice copies
   - Original, Duplicate, Triplicate
   - Different formats for each copy

2. **Copy Labeling**:
   - Automatic copy labeling
   - Clear identification of each copy
   - Professional appearance

---

## 🔒 **Document Submission Control**

### **How Submission Control Works**

#### **Step 1: Enable Restrictions**
1. **Open BNS Settings**:
   - Navigate to **Setup > BNS Settings**
   - Go to **Submission Control** tab

2. **Enable Restriction**:
   - Check **Restrict Document Submission**
   - Save the settings

#### **Step 2: Configure Override Roles**
1. **Add Override Roles**:
   - Click **Add Row** in Override Roles table
   - Select roles that can submit documents
   - Common roles: System Manager, Accounts Manager

2. **Role Assignment**:
   - Assign appropriate roles to users
   - Users with override roles can submit documents
   - Other users can only save as draft

#### **Step 3: Test the System**
1. **Test with Restricted User**:
   - Login as a user without override role
   - Try to submit a document
   - Should see restriction message

2. **Test with Override User**:
   - Login as a user with override role
   - Try to submit a document
   - Should work normally

### **Document Categories**

#### **Stock Documents**
- **Stock Entry**: Material transfers and adjustments
- **Stock Reconciliation**: Stock count adjustments
- **Sales Invoice** (with stock update): Affects inventory
- **Purchase Invoice** (with stock update): Affects inventory
- **Delivery Note**: Stock out transactions
- **Purchase Receipt**: Stock in transactions

#### **Transaction Documents**
- **Sales Invoice** (without stock update): Financial only
- **Purchase Invoice** (without stock update): Financial only
- **Journal Entry**: General ledger entries
- **Payment Entry**: Payment transactions

#### **Order Documents**
- **Sales Order**: Customer orders
- **Purchase Order**: Supplier orders
- **Payment Request**: Payment requests

### **Override Permissions**

#### **System Manager**
- **Always Has Access**: Can submit any document
- **No Configuration Needed**: Automatically has override
- **Use Case**: System administrators

#### **Custom Roles**
- **Department Heads**: Can submit department documents
- **Accountants**: Can submit financial documents
- **Managers**: Can submit order documents

#### **Granular Control**
- **Document Type**: Control by specific document types
- **User Level**: Control by individual users
- **Time-based**: Control by time periods

---

## 🔄 **Internal Transfer Management**

### **Setting Up Internal Customers**

#### **Step 1: Create Internal Customer**
1. **Navigate to Customer**:
   - Go to **Selling > Customer**
   - Click **New**

2. **Configure Customer**:
   - **Customer Name**: Internal customer name
   - **Customer Type**: Company
   - **Is Internal Customer**: ✅ Check this box
   - **Represents Company**: Select the company this customer represents

3. **GSTIN Configuration**:
   - **GSTIN**: Enter the GSTIN of the represented company
   - **PAN**: Enter the PAN of the represented company

#### **Step 2: Configure Addresses**
1. **Billing Address**:
   - Create billing address for the internal customer
   - Include complete address details
   - Add GSTIN if applicable

2. **Shipping Address**:
   - Create shipping address if different
   - Include delivery instructions
   - Add contact information

### **Setting Up Internal Suppliers**

#### **Step 1: Create Internal Supplier**
1. **Navigate to Supplier**:
   - Go to **Buying > Supplier**
   - Click **New**

2. **Configure Supplier**:
   - **Supplier Name**: Internal supplier name
   - **Supplier Type**: Company
   - **Is Internal Supplier**: ✅ Check this box
   - **Represents Company**: Select the company this supplier represents

3. **GSTIN Configuration**:
   - **GSTIN**: Enter the GSTIN of the represented company
   - **PAN**: Enter the PAN of the represented company

### **Internal Transfer Process**

#### **Step 1: Create Delivery Note**
1. **Navigate to Delivery Note**:
   - Go to **Stock > Delivery Note**
   - Click **New**

2. **Configure Delivery Note**:
   - **Customer**: Select internal customer
   - **Items**: Add items to be transferred
   - **Warehouse**: Select source warehouse
   - **Save**: Save the delivery note

#### **Step 2: Generate Purchase Receipt**
1. **Create Purchase Receipt**:
   - In the Delivery Note, click **Create Purchase Receipt**
   - System automatically creates Purchase Receipt
   - All details are mapped automatically

2. **Verify Purchase Receipt**:
   - Check all details are correct
   - Verify supplier and customer mapping
   - Confirm warehouse assignments

#### **Step 3: Submit Documents**
1. **Submit Delivery Note**:
   - Submit the Delivery Note
   - Status updates automatically

2. **Submit Purchase Receipt**:
   - Submit the Purchase Receipt
   - Both documents are now linked

### **GST Validation**

#### **Automatic GST Validation**
- **GSTIN Comparison**: System compares GSTINs automatically
- **Tax Calculation**: Automatic tax calculation based on GSTINs
- **Compliance**: Ensures GST compliance for internal transfers

#### **Manual GST Configuration**
1. **Tax Templates**:
   - Configure appropriate tax templates
   - Set up GST rates correctly
   - Ensure compliance with tax laws

2. **Tax Calculation**:
   - Verify tax calculations
   - Check GST summary tables
   - Ensure accuracy of tax amounts

---

## 📊 **Reports and Analytics**

### **Available Reports**

#### **1. Almonds Sorting Report**
**Purpose**: Track sorting and processing activities for food processing businesses

**Features**:
- **Batch-wise Tracking**: Track individual batches
- **Quality Metrics**: Monitor quality parameters
- **Processing Efficiency**: Measure processing efficiency
- **Cost Analysis**: Analyze processing costs

**How to Use**:
1. **Navigate to Report**:
   - Go to **Reports > Business Needed Solutions > Almonds Sorting Report**

2. **Set Filters**:
   - **Batch No**: Select specific batch
   - **Item Code**: Select item to analyze
   - **Date Range**: Set date range for analysis

3. **Generate Report**:
   - Click **Generate Report**
   - View results in table format
   - Export to Excel if needed

#### **2. Financial Reports**

**Bank GL Report**:
- **Purpose**: Comprehensive bank ledger analysis
- **Features**: Detailed bank transaction tracking
- **Use Case**: Bank reconciliation and analysis

**Party GL Report**:
- **Purpose**: Customer and supplier ledger analysis
- **Features**: Detailed party transaction tracking
- **Use Case**: Customer/supplier account analysis

**Accounts Payable Summary**:
- **Purpose**: Enhanced payable reporting
- **Features**: Detailed payable analysis
- **Use Case**: Payable management and analysis

**Accounts Receivable Summary**:
- **Purpose**: Enhanced receivable reporting
- **Features**: Detailed receivable analysis
- **Use Case**: Receivable management and analysis

#### **3. Compliance Reports**

**PAN Validation Report**:
- **Purpose**: Track PAN uniqueness compliance
- **Features**: Identify duplicate PAN numbers
- **Use Case**: Compliance monitoring and reporting

**GST Compliance Report**:
- **Purpose**: GST-related compliance reporting
- **Features**: GST calculation and reporting
- **Use Case**: Tax compliance and reporting

**Document Submission Report**:
- **Purpose**: Track submission activities
- **Features**: Monitor document submission patterns
- **Use Case**: Audit and compliance tracking

### **Report Configuration**

#### **Step 1: Access Reports**
1. **Navigate to Reports**:
   - Go to **Reports** section in ERPNext
   - Find **Business Needed Solutions** category

2. **Select Report**:
   - Choose the report you want to generate
   - Click on the report name

#### **Step 2: Configure Filters**
1. **Set Parameters**:
   - Configure report-specific filters
   - Set date ranges if applicable
   - Select relevant options

2. **Apply Filters**:
   - Click **Apply Filters**
   - Verify filter settings

#### **Step 3: Generate and Export**
1. **Generate Report**:
   - Click **Generate Report**
   - Wait for report to load

2. **Export Options**:
   - **Excel**: Export to Excel format
   - **PDF**: Export to PDF format
   - **Print**: Print directly

---

## 🔧 **Troubleshooting**

### **Common Issues and Solutions**

#### **Print Format Issues**

**Problem**: Print formats not working
**Solutions**:
1. **Check BNS Settings**:
   - Verify print format mappings
   - Check rate display settings
   - Ensure settings are saved

2. **Check Browser Settings**:
   - Allow popups for your ERPNext site
   - Clear browser cache
   - Try different browser

3. **Verify Logo Configuration**:
   - Check logo is uploaded correctly
   - Verify logo field is set
   - Test with different logo format

**Problem**: Bank details not showing
**Solutions**:
1. **Check Bank Account**:
   - Verify bank account exists
   - Check "Is Default" is set
   - Ensure all details are filled

2. **Check Company Settings**:
   - Verify company is set correctly
   - Check default currency
   - Ensure company details are complete

#### **Submission Control Issues**

**Problem**: Submission restrictions not working
**Solutions**:
1. **Check BNS Settings**:
   - Verify restriction is enabled
   - Check override roles are set
   - Ensure settings are saved

2. **Check User Permissions**:
   - Verify user has correct roles
   - Check role assignments
   - Test with different users

3. **Check Document Type**:
   - Verify document is in correct category
   - Check document status
   - Ensure document is not already submitted

#### **Internal Transfer Issues**

**Problem**: Internal transfers failing
**Solutions**:
1. **Check Customer/Supplier Setup**:
   - Verify "Is Internal Customer/Supplier" is checked
   - Check company assignments
   - Ensure GSTIN is configured

2. **Check Address Configuration**:
   - Verify addresses are set up correctly
   - Check GSTIN in addresses
   - Ensure contact information is complete

3. **Check Tax Configuration**:
   - Verify tax templates are set up
   - Check GST rates are correct
   - Ensure tax calculation is working

#### **Validation Issues**

**Problem**: PAN uniqueness errors
**Solutions**:
1. **Check PAN Configuration**:
   - Verify PAN is entered correctly
   - Check for duplicate PAN numbers
   - Ensure PAN format is correct

2. **Check BNS Settings**:
   - Verify PAN uniqueness is enabled
   - Check validation settings
   - Ensure settings are saved

**Problem**: Expense account validation errors
**Solutions**:
1. **Check Item Configuration**:
   - Verify item is non-stock item
   - Check expense account is set
   - Ensure account is active

2. **Check BNS Settings**:
   - Verify expense account validation is enabled
   - Check validation settings
   - Ensure settings are saved

### **Debug Mode**

#### **Enable Debug Logging**
1. **Access System Console**:
   - Go to **Setup > System Console**
   - Or use bench console

2. **Enable Debug Mode**:
   ```python
   import logging
   logging.getLogger('business_needed_solutions').setLevel(logging.DEBUG)
   ```

3. **Check Logs**:
   - Monitor system logs
   - Look for BNS-related messages
   - Identify specific issues

#### **Common Debug Commands**
1. **Check BNS Settings**:
   ```python
   frappe.get_doc("BNS Settings")
   ```

2. **Check User Permissions**:
   ```python
   frappe.get_roles(frappe.session.user)
   ```

3. **Check Document Status**:
   ```python
   frappe.get_doc("Document Type", "Document Name")
   ```

---

## 💡 **Best Practices**

### **Configuration Best Practices**

#### **BNS Settings**
1. **Start Simple**:
   - Begin with basic settings
   - Enable features gradually
   - Test each feature before enabling

2. **Document Your Configuration**:
   - Keep records of your settings
   - Document any customizations
   - Maintain configuration backups

3. **Regular Reviews**:
   - Review settings periodically
   - Update configurations as needed
   - Monitor system performance

#### **Print Formats**
1. **Standardize Formats**:
   - Use consistent formats across documents
   - Maintain professional appearance
   - Ensure readability

2. **Test Formats**:
   - Test all print formats
   - Verify all information displays correctly
   - Check different document types

3. **Maintain Branding**:
   - Keep logos updated
   - Ensure consistent branding
   - Maintain professional appearance

#### **User Management**
1. **Role Assignment**:
   - Assign roles based on job functions
   - Limit override permissions
   - Regular role reviews

2. **Training**:
   - Train users on new features
   - Provide user guides
   - Regular training sessions

3. **Monitoring**:
   - Monitor user activities
   - Track submission patterns
   - Regular access reviews

### **Operational Best Practices**

#### **Daily Operations**
1. **Regular Checks**:
   - Check system status daily
   - Monitor error logs
   - Verify data integrity

2. **Backup Procedures**:
   - Regular data backups
   - Configuration backups
   - Test restore procedures

3. **Performance Monitoring**:
   - Monitor system performance
   - Track response times
   - Optimize as needed

#### **Compliance Management**
1. **Regular Audits**:
   - Conduct regular compliance audits
   - Review submission patterns
   - Verify data accuracy

2. **Documentation**:
   - Maintain audit trails
   - Document compliance procedures
   - Keep records updated

3. **Training**:
   - Regular compliance training
   - Update procedures as needed
   - Monitor compliance status

### **Security Best Practices**

#### **Access Control**
1. **Principle of Least Privilege**:
   - Grant minimum necessary permissions
   - Regular permission reviews
   - Remove unused permissions

2. **Role Management**:
   - Define clear role responsibilities
   - Regular role reviews
   - Document role assignments

3. **User Management**:
   - Regular user account reviews
   - Remove inactive accounts
   - Monitor user activities

#### **Data Protection**
1. **Data Backup**:
   - Regular automated backups
   - Test backup procedures
   - Secure backup storage

2. **Access Logging**:
   - Enable comprehensive logging
   - Monitor access patterns
   - Regular log reviews

3. **Security Updates**:
   - Regular security updates
   - Monitor security advisories
   - Apply patches promptly

---

## 📞 **Support and Contact**

### **Getting Help**

#### **Documentation**
- **User Guides**: Comprehensive user documentation
- **Video Tutorials**: Step-by-step video guides
- **FAQ Section**: Common questions and answers

#### **Technical Support**
- **Email Support**: sagar1ratan1garg1@gmail.com
- **Response Time**: Within 24-48 hours
- **Support Hours**: Business hours (IST)

#### **Training and Consulting**
- **User Training**: Available training sessions
- **Customization**: Custom development services
- **Business Consulting**: Process optimization consulting

### **Commercial Licensing**

#### **License Types**
- **Standard License**: Basic features for small businesses
- **Professional License**: Advanced features for medium businesses
- **Enterprise License**: Full features for large organizations

#### **Pricing Information**
- **Contact for Pricing**: Email for detailed pricing
- **Volume Discounts**: Available for multiple licenses
- **Annual Maintenance**: Includes updates and support

#### **Custom Development**
- **Feature Development**: Custom feature development
- **Integration Services**: Third-party integrations
- **Migration Services**: Data migration assistance

---

**This comprehensive guide covers all aspects of using Business Needed Solutions. For additional support or questions, please contact our support team.** 