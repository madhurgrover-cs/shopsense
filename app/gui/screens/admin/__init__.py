"""Admin screens, one file each. Every change an admin makes goes through a service
function (catalog_service, order_service, coupon_service), which checks the user is an
admin and writes the audit log entry in the same transaction as the change."""
