# Print Format Configuration Guide

## 🖨️ **Complete Print Format Setup Guide**

This guide provides detailed instructions for configuring all print formats in Business Needed Solutions, including company branding, bank details, and advanced customization options.

---

## 📋 **Available Print Formats**

### **1. Sales Invoice Formats**

#### **BNS SI Dynamic V1**
**Document Type**: Sales Invoice
**Features**:
- ✅ Company logo and branding
- ✅ Bank account details
- ✅ GST summary tables
- ✅ e-Invoice QR codes
- ✅ Multiple copy support
- ✅ Payment terms display
- ✅ Vehicle and transporter details
- ✅ Professional layout

#### **Configuration Options**:
- **Rate Display**: Inclusive/Exclusive tax rates
- **Discount Display**: Single or triple discount
- **Copy Types**: Original, Duplicate, Triplicate
- **GST Summary**: Automatic GST calculation and display

### **2. Delivery Note Formats**

#### **BNS DN Dynamic V1**
**Document Type**: Delivery Note
**Features**:
- ✅ Vehicle and transporter details
- ✅ e-Waybill integration
- ✅ Shipping and dispatch information
- ✅ Terms of delivery
- ✅ Professional layout
- ✅ Company branding

#### **Configuration Options**:
- **Vehicle Details**: Automatic vehicle information
- **Transporter Details**: Transporter name and GST ID
- **Shipping Information**: Complete shipping details
- **Terms**: Custom terms of delivery

### **3. Purchase Order Formats**

#### **BNS PO Dynamic V1**
**Document Type**: Purchase Order
**Features**:
- ✅ Supplier information
- ✅ Delivery terms
- ✅ Payment terms
- ✅ Professional branding
- ✅ Company details

#### **BNS PO V1**
**Document Type**: Purchase Order
**Features**:
- ✅ Standard purchase order layout
- ✅ Supplier details
- ✅ Professional formatting

### **4. Sales Order Formats**

#### **BNS SO Dynamic V1**
**Document Type**: Sales Order
**Features**:
- ✅ Customer information
- ✅ Delivery schedules
- ✅ Professional layout
- ✅ Company branding

---

## 🏢 **Company Branding Setup**

### **Step 1: Company Logo Configuration**

#### **Logo Requirements**
- **Format**: PNG, JPG, or GIF
- **Size**: 200x200 pixels (recommended)
- **Quality**: High resolution for professional appearance
- **Background**: Transparent or white background
- **File Size**: Maximum 2MB

#### **Upload Process**
1. **Navigate to Company Settings**:
   - Go to **Setup > Company**
   - Select your company

2. **Upload Logo**:
   - Find the **Logo for Printing** field
   - Click **Attach** or **Choose File**
   - Select your logo file
   - Click **Upload**

3. **Verify Display**:
   - Print any document to verify logo appears
   - Logo will appear in the top-left corner of all formats

#### **Logo Display Options**
- **Position**: Top-left corner (default)
- **Size**: Automatic scaling to fit
- **Alignment**: Left-aligned
- **Spacing**: Proper spacing from text

### **Step 2: Company Information Setup**

#### **Company Details**
1. **Company Name**: Set in Company settings
2. **Address**: Complete company address
3. **Contact Information**: Phone, email, website
4. **GSTIN**: Company GST number
5. **PAN**: Company PAN number

#### **Address Configuration**
- **Address Line 1**: Street address
- **Address Line 2**: Additional address details
- **City**: Company city
- **State**: Company state
- **Pincode**: Postal code
- **Country**: Company country

---

## 🏦 **Bank Details Configuration**

### **Step 1: Bank Account Setup**

#### **Create Bank Account**
1. **Navigate to Chart of Accounts**:
   - Go to **Accounting > Chart of Accounts**
   - Find or create your bank account

2. **Configure Bank Details**:
   - **Account Name**: Your account name
   - **Bank**: Bank name
   - **Account Number**: Your account number
   - **Branch Code (IFSC)**: IFSC code for Indian banks
   - **IBAN**: For international accounts

#### **Set Default Account**
1. **Mark as Default**:
   - In the bank account, check **Is Default**
   - This account will appear on all invoices

2. **Multiple Accounts**:
   - You can have multiple bank accounts
   - Only the default account appears on formats
   - Change default as needed

### **Step 2: Bank Details Display**

#### **Information Displayed**
- **Account Name**: Full account holder name
- **Bank Name**: Complete bank name
- **Account Number**: Masked account number (for security)
- **IFSC Code**: Branch IFSC code
- **Branch Details**: Branch name and location

#### **Security Features**
- **Account Number Masking**: Only last 4 digits visible
- **Secure Display**: Sensitive information protected
- **Professional Format**: Clean, professional appearance

---

## ⚙️ **Print Format Settings**

### **BNS Settings Configuration**

#### **Print Options Tab**
1. **Rate Display Settings**:
   - **Rate (Incl Tax)**: Show rates including tax
   - **Rate (Excl Tax)**: Show rates excluding tax
   - **Secondary Rate Display**: Additional rate information

2. **Format Mapping**:
   - **Doctype Map**: Select document type
   - **Print Format**: Select format to use
   - **Priority**: Set format priority

#### **Rate Display Options**

##### **Inclusive Tax Rates**
- **Display**: Shows rates including GST
- **Calculation**: Automatic tax calculation
- **Use Case**: Customer-facing documents
- **Format**: "₹100.00 (Incl. Tax)"

##### **Exclusive Tax Rates**
- **Display**: Shows rates excluding GST
- **Calculation**: Base price display
- **Use Case**: Internal documents
- **Format**: "₹85.47 (Excl. Tax)"

##### **Secondary Rate Display**
- **Print UOM**: Shows rates in different units
- **Weight UOM**: Shows rates per kilogram
- **Use Case**: Manufacturing businesses
- **Format**: "₹100.00/kg"

### **Discount Configuration**

#### **Single Discount Mode**
- **Display**: Single discount percentage
- **Field**: "Discount %" column
- **Calculation**: Simple percentage discount
- **Use Case**: Standard business practices

#### **Triple Compounded Mode**
- **Display**: Three separate discount fields
- **Fields**: D1, D2, D3 columns
- **Calculation**: Compounded discount calculation
- **Use Case**: Complex discount structures

---

## 🎨 **Advanced Format Features**

### **Document Copy Support**

#### **Multiple Copy Types**
1. **Original**: First copy for customer
2. **Duplicate**: Second copy for records
3. **Triplicate**: Third copy for internal use
4. **Custom Copies**: Additional copy types

#### **Copy Configuration**
- **Copy Labeling**: Automatic copy identification
- **Format Variations**: Different formats for different copies
- **Print Options**: Select which copies to print

### **GST Summary Tables**

#### **Automatic GST Calculation**
- **CGST**: Central GST calculation
- **SGST**: State GST calculation
- **IGST**: Integrated GST calculation
- **Total GST**: Combined GST amount

#### **GST Summary Display**
- **Rate-wise Summary**: GST by tax rate
- **Total Summary**: Overall GST summary
- **Compliance**: GST compliance information

### **e-Invoice Integration**

#### **QR Code Display**
- **Automatic Generation**: QR codes generated automatically
- **e-Invoice Data**: Embedded invoice data
- **Compliance**: e-Invoice compliance features

#### **e-Invoice Details**
- **IRN**: Invoice Reference Number
- **Ack No**: Acknowledgment number
- **Ack Date**: Acknowledgment date
- **QR Code**: Scannable QR code

### **Vehicle and Transporter Details**

#### **Vehicle Information**
- **Vehicle Number**: Registration number
- **Transporter**: Transporter name
- **GST Transporter ID**: Transporter GST ID
- **Transport Mode**: Mode of transport

#### **Shipping Information**
- **Dispatch Address**: Dispatch location
- **Shipping Address**: Delivery location
- **Terms of Delivery**: Delivery terms
- **Destination**: Final destination

---

## 🔧 **Customization Options**

### **CSS Styling**

#### **Available CSS Classes**
```css
/* Company branding */
.company-logo { width: 100%; }
.company-name { font-weight: bold; }

/* Bank details */
.bank-details { font-size: 12px; }
.account-info { font-weight: bold; }

/* Document layout */
.print-heading { border-bottom: 1px solid #000; }
.party-details-table { table-layout: fixed; }

/* Item table */
.e-invoice-table { border: 1px solid #000; }
.item-det { font-size: 0.8em; }

/* GST summary */
.gst-summary { font-weight: bold; }
.tax-breakdown { font-size: 11px; }
```

#### **Custom Styling**
1. **Color Schemes**: Customize colors
2. **Font Sizes**: Adjust font sizes
3. **Layout**: Modify layout structure
4. **Spacing**: Adjust spacing and margins

### **Template Customization**

#### **HTML Templates**
- **Header Section**: Company and document information
- **Party Details**: Customer/supplier information
- **Item Table**: Product details and pricing
- **Summary Section**: Totals and tax information
- **Footer Section**: Terms and signatures

#### **Dynamic Content**
- **Conditional Display**: Show/hide based on conditions
- **Calculated Fields**: Automatic calculations
- **Data Integration**: ERPNext data integration
- **Custom Logic**: Business-specific logic

---

## 📱 **Mobile and Web Compatibility**

### **Responsive Design**
- **Mobile Friendly**: Optimized for mobile devices
- **Tablet Support**: Tablet-optimized layouts
- **Desktop**: Full desktop functionality
- **Print Optimization**: Print-optimized layouts

### **Browser Compatibility**
- **Chrome**: Full support
- **Firefox**: Full support
- **Safari**: Full support
- **Edge**: Full support

---

## 🔒 **Security Features**

### **Data Protection**
- **Account Masking**: Sensitive data protection
- **Access Control**: Role-based access
- **Audit Trail**: Complete activity logging
- **Secure Storage**: Encrypted data storage

### **Compliance Features**
- **GST Compliance**: Built-in GST compliance
- **Tax Compliance**: Tax calculation compliance
- **Document Compliance**: Document format compliance
- **Audit Support**: Audit trail support

---

## 📊 **Performance Optimization**

### **Print Speed**
- **Optimized Templates**: Fast rendering
- **Efficient CSS**: Optimized styling
- **Minimal Dependencies**: Reduced load times
- **Caching**: Template caching

### **Resource Usage**
- **Lightweight**: Minimal resource usage
- **Efficient**: Optimized for performance
- **Scalable**: Handles large documents
- **Reliable**: Stable performance

---

## 🛠️ **Troubleshooting**

### **Common Issues**

#### **Logo Not Displaying**
1. **Check Upload**: Verify logo is uploaded correctly
2. **Check Field**: Ensure "Logo for Printing" field is set
3. **Check Format**: Verify logo format is supported
4. **Check Size**: Ensure logo size is appropriate

#### **Bank Details Missing**
1. **Check Bank Account**: Verify bank account exists
2. **Check Default**: Ensure account is marked as default
3. **Check Details**: Verify all bank details are filled
4. **Check Company**: Ensure correct company is selected

#### **Format Not Working**
1. **Check BNS Settings**: Verify format mapping
2. **Check Permissions**: Ensure user has permissions
3. **Check Browser**: Try different browser
4. **Check Cache**: Clear browser cache

### **Debug Steps**
1. **Enable Debug Mode**: Enable debug logging
2. **Check Logs**: Review system logs
3. **Test Formats**: Test each format individually
4. **Verify Settings**: Check all configuration settings

---

## 📞 **Support and Contact**

### **Technical Support**
- **Email**: sagar1ratan1garg1@gmail.com
- **Response Time**: Within 24-48 hours
- **Support Hours**: Business hours (IST)

### **Customization Services**
- **Format Customization**: Custom format development
- **Branding Integration**: Custom branding setup
- **Feature Development**: Custom feature development
- **Integration Services**: Third-party integrations

### **Training and Consulting**
- **User Training**: Format configuration training
- **Best Practices**: Implementation best practices
- **Process Optimization**: Business process optimization
- **Compliance Consulting**: Compliance and audit support

---

**This comprehensive guide covers all aspects of print format configuration in Business Needed Solutions. For additional support or customization services, please contact our support team.** 