import os
import subprocess

def main():
    filepath = "business_needed_solutions/hooks.py"
    if not os.path.exists(filepath):
        print("hooks.py not found.")
        return
        
    with open(filepath, "r") as f:
        content = f.read()

    # Define target conflict block
    target = """<<<<<<< HEAD
app_include_js = [
                  "/assets/business_needed_solutions/js/purchase_invoice_form.js?v=216",
                  "/assets/business_needed_solutions/js/purchase_receipt_form.js?v=51",
=======
app_include_js = ["/assets/business_needed_solutions/js/sales_invoice_form.js?v=122",
                  "/assets/business_needed_solutions/js/purchase_invoice_form.js?v=219",
                  "/assets/business_needed_solutions/js/purchase_receipt_form.js?v=52",
>>>>>>> upstream/main"""

    resolved = """app_include_js = [
                  "/assets/business_needed_solutions/js/purchase_invoice_form.js?v=219",
                  "/assets/business_needed_solutions/js/purchase_receipt_form.js?v=52","""

    if target in content:
        content = content.replace(target, resolved)
        with open(filepath, "w") as f:
            f.write(content)
        print("Conflict resolved in hooks.py!")
        
        # Git commands
        subprocess.run(["git", "add", filepath], check=True)
        subprocess.run(["git", "commit", "-m", "merge: resolve hooks.py conflict"], check=True)
        subprocess.run(["git", "push", "upstream", "feat/somil"], check=True)
        print("Committed and pushed resolution to GitHub successfully!")
    else:
        print("Conflict block not found or already resolved.")

if __name__ == "__main__":
    main()
