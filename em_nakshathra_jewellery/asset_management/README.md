# Asset Management Module for Odoo 17.0

A comprehensive asset management solution for Odoo that helps businesses track, manage, and maintain their physical assets throughout their lifecycle.

## 🚀 Features

### Core Asset Management
- **Asset Lifecycle Tracking**: From acquisition to disposal
- **Dual Asset Types**: Single assets and multiple stock-managed assets
- **Financial Tracking**: Purchase price, depreciation, and maintenance costs
- **Asset Classification**: Custom asset types with configurable depreciation rules
- **Tagging System**: Organize assets with customizable tags

### Asset Operations
- **Transfer Management**: Employee assignment and return tracking
- **Maintenance & Repair**: Vendor management and service tracking
- **Warranty Management**: Expiry tracking with visual status indicators
- **Document Management**: File attachments for asset documentation

### Financial Features
- **Automated Depreciation**: Multiple depreciation methods (percentage, fixed amount)
- **Flexible Depreciation**: Yearly, monthly, or daily frequency options
- **Cost Tracking**: Maintenance and repair cost accumulation
- **Current Value Calculation**: Real-time book value after depreciation

### Reporting & Analytics
- **Stock Movement Reports**: Track asset transfers and returns
- **Depreciation Reports**: Monitor asset value changes over time
- **Maintenance History**: Complete service and repair records
- **Asset Performance**: Utilization and cost analysis

## 📋 Requirements

- Odoo 17.0 or later
- Access to the following Odoo modules:
  - `base` (Core Odoo functionality)
  - `product` (Product management)
  - `hr` (Human resources/Employee management)
  - `account` (Accounting functionality)

## 🛠️ Installation

1. **Download the module** to your Odoo addons directory
2. **Update the addons list** in Odoo
3. **Install the module** from the Apps menu
4. **Configure user access** by assigning users to appropriate groups

## 🎯 Demo Data

The module includes comprehensive demo data to help you understand its capabilities:

### Asset Types
- **Office Equipment**: 20% yearly depreciation
- **Vehicles**: 25% yearly depreciation  
- **Office Furniture**: 15% yearly depreciation
- **Computers & IT**: 33.33% yearly depreciation
- **Buildings**: 5% yearly depreciation

### Sample Assets
- **Single Assets**: Laptop, Desk, Vehicle
- **Multiple Assets**: Office Chairs (50 units), Monitors (25 units), Printers (10 units)

### Sample Data Includes
- Asset types with realistic depreciation rates
- Vendor information with contact details
- Asset tags for organization
- Transfer entries showing asset assignments
- Maintenance records with costs
- Depreciation entries demonstrating calculations

## 🔧 Configuration

### 1. Asset Types Setup
Configure asset types with appropriate depreciation rules:
- **Depreciation Frequency**: Yearly, monthly, or daily
- **Depreciation Method**: Percentage or fixed amount
- **Depreciation Rate**: Set appropriate rates for your business
- **Maximum Entries**: Control how many depreciation entries can be created

### 2. User Groups & Permissions
The module creates several user groups:
- **Assets User Group**: Basic asset management
- **Transfer User Group**: Asset assignment and returns
- **Maintenance User Group**: Maintenance and repair operations
- **Depreciation User Group**: Depreciation management
- **Vendor User Group**: Vendor information management

### 3. Scheduled Actions
- **Depreciation Generation**: Automatically runs daily to calculate depreciation
- **Asset Sequences**: Automatic numbering for assets and transfers

## 📊 Usage Examples

### Creating a New Asset
1. Navigate to **Assets > Assets**
2. Click **Create**
3. Select asset type and model type
4. Enter purchase details and vendor information
5. Configure depreciation settings
6. Save the asset

### Assigning an Asset
1. Go to the asset record
2. Navigate to the **Transfer** tab
3. Click **Create** to add a transfer entry
4. Select employee and assign date
5. Set status to "Assigned"

### Recording Maintenance
1. Access the asset record
2. Go to the **Maintenance** tab
3. Create a maintenance entry
4. Specify vendor, dates, and costs
5. Upload related documents

### Viewing Depreciation
1. Check the **Depreciation** tab on asset records
2. View accumulated depreciation amounts
3. Monitor current book value
4. Review depreciation history

## 🔍 Key Views

### Asset Form View
- **Status Bar**: Visual asset lifecycle status
- **Basic Information**: Asset type, model type, tags
- **Financial Information**: Purchase price, current value
- **Depreciation Settings**: Enable/disable and track depreciation
- **Notebook Tabs**: Transfer, maintenance, and depreciation records

### Asset List View
- **Filters**: By asset type, status, model type
- **Grouping**: By various criteria
- **Search**: Quick asset lookup
- **Status Indicators**: Visual status representation

### Dashboard Views
- **Asset Overview**: Summary of all assets
- **Stock Status**: Current availability
- **Financial Summary**: Total values and depreciation

## 📈 Business Benefits

- **Improved Asset Visibility**: Complete tracking of all company assets
- **Cost Control**: Monitor depreciation and maintenance expenses
- **Compliance**: Proper asset accounting and reporting
- **Efficiency**: Streamlined asset assignment and return processes
- **Planning**: Better asset lifecycle and replacement planning

## 🆘 Support

For technical support or questions:
- **Developer**: WebbyCrown Solutions
- **Website**: https://www.webbycrown.com
- **License**: LGPL-3

## 🔄 Version History

- **17.0**: Initial release with comprehensive asset management features
- **Future**: Planned enhancements including barcode support and advanced reporting

## 📝 License

This module is licensed under LGPL-3, allowing you to:
- Use the module in commercial applications
- Modify the source code
- Distribute modified versions
- Use in proprietary software

---

**Note**: Demo data is automatically loaded when installing the module with demo data enabled. This provides a complete working example to help you understand the module's capabilities.
