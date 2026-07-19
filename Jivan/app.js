// Works in two places with zero changes:
//  - Node (for local testing): React comes from require('react')
//  - Browser: React comes from window.React (loaded via CDN script tag)
// No JSX, no Babel, no build step — the browser runs this file exactly
// as written, no in-browser translation step to fail.

(function (root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = factory(require("react"), require("react-dom"));
    } else {
        root.JivanApp = factory(root.React, root.ReactDOM);
    }
})(typeof self !== "undefined" ? self : this, function (React, ReactDOM) {

    var h = React.createElement;

    // Renders content into #print-root (a sibling of #root, outside
    // .app-shell) instead of inline in the component tree — see the
    // note in index.html for why: a hidden ancestor hides all its
    // descendants regardless of their own CSS, so the print sheet
    // must live outside .app-shell to still show once that's hidden
    // for printing. Guarded because `document` doesn't exist when
    // this file is loaded under Node for testing.
    function renderPrintPortal(content) {
        if (typeof document === "undefined") return null;
        var target = document.getElementById("print-root");
        if (!target) return null;
        return ReactDOM.createPortal(content, target);
    }

    var useState = React.useState;
    var useEffect = React.useEffect;
    var useCallback = React.useCallback;

    var NAV_ITEMS = [
        { key: "order-entry", label: "Order Entry", icon: "\u2795", roles: ["Sales Coordinator", "Admin"] },
        { key: "order-tracker", label: "Order Tracker", icon: "\uD83D\uDCCB", roles: null },
        { key: "update-status", label: "Update Status", icon: "\uD83D\uDD04", roles: null },
        { key: "dashboard", label: "Dashboard", icon: "\uD83D\uDCCA", roles: null },
        { key: "admin", label: "Admin", icon: "\u2699\uFE0F", roles: ["Admin"] }
    ];

    var PAGE_META = {
        "order-entry": { title: "New Order Entry", note: "Create a multi-item order for a customer." },
        "order-tracker": { title: "Order Tracker", note: "View, filter, and drill into every order." },
        "update-status": { title: "Update Status", note: "Move orders through the fulfilment workflow." },
        "dashboard": { title: "Dashboard", note: "Key metrics and breakdowns." },
        "admin": { title: "Admin", note: "Manage customers, products, warehouses, and users." }
    };

    var REGIONS = ["North", "South", "East", "West"];

    // ---- Master data access ----
    // Postgres error codes are consistent and machine-checkable —
    // translate the common ones into plain language instead of
    // showing raw constraint-violation text to end users.
    function friendlyErrorMessage(error, itemLabel) {
        if (!error) return "";
        if (error.code === "23503") {
            return "Can't do that \u2014 \"" + itemLabel + "\" is linked to existing orders. " +
                "Remove or reassign those orders first.";
        }
        if (error.code === "23505") {
            return "\"" + itemLabel + "\" already exists \u2014 use a different name.";
        }
        return error.message;
    }

    function fetchCustomers(supabase) {
        return supabase.from("customers").select("*").order("name")
            .then(function (r) { return r.data || []; });
    }
    function insertCustomer(supabase, values) {
        return supabase.from("customers").insert({
            name: values.name, region: values.region, rsm: values.rsm
        });
    }
    function updateCustomer(supabase, id, values) {
        return supabase.from("customers").update({
            name: values.name, region: values.region, rsm: values.rsm
        }).eq("customer_id", id);
    }
    function deleteCustomer(supabase, id) {
        return supabase.from("customers").delete().eq("customer_id", id);
    }

    function fetchProducts(supabase) {
        return supabase.from("products").select("*").order("name")
            .then(function (r) { return r.data || []; });
    }
    // Only active products — used by Order Entry so a deactivated
    // product can no longer be selected for new orders, while
    // Admin's fetchProducts above still shows everything (so
    // deactivated products remain visible there to be reactivated).
    function fetchActiveProducts(supabase) {
        return supabase.from("products").select("*").eq("is_active", true).order("name")
            .then(function (r) { return r.data || []; });
    }
    function insertProduct(supabase, values) {
        return supabase.from("products").insert({ name: values.name });
    }
    function updateProduct(supabase, id, values) {
        return supabase.from("products").update({ name: values.name }).eq("product_id", id);
    }
    // Deletes the product only if it has never appeared in any
    // order. If it has order history, deactivates it instead (so
    // it disappears from Order Entry's picker, but past orders and
    // this row itself are left untouched).
    function deleteOrDeactivateProduct(supabase, item) {
        return supabase.from("order_items").select("*", { count: "exact", head: true }).eq("item", item.name)
            .then(function (countResult) {
                if (countResult.error) return countResult;
                if ((countResult.count || 0) === 0) {
                    return supabase.from("products").delete().eq("product_id", item.product_id)
                        .then(function (delResult) {
                            if (delResult.error) return delResult;
                            return { error: null, message: "Deleted." };
                        });
                }
                return supabase.from("products").update({ is_active: false }).eq("product_id", item.product_id)
                    .then(function (updResult) {
                        if (updResult.error) return updResult;
                        return { error: null, message: "Deactivated \u2014 this product has order history, so it can't be fully deleted. It won't appear as an option for new orders." };
                    });
            });
    }
    function reactivateProduct(supabase, item) {
        return supabase.from("products").update({ is_active: true }).eq("product_id", item.product_id)
            .then(function (result) {
                if (result.error) return result;
                return { error: null, message: "Reactivated." };
            });
    }

    function fetchWarehouses(supabase) {
        return supabase.from("warehouses").select("*").order("name")
            .then(function (r) { return r.data || []; });
    }
    function insertWarehouse(supabase, values) {
        return supabase.from("warehouses").insert({
            name: values.name, region: values.region
        });
    }
    function updateWarehouse(supabase, id, values) {
        return supabase.from("warehouses").update({
            name: values.name, region: values.region
        }).eq("warehouse_id", id);
    }
    function deleteWarehouse(supabase, id) {
        return supabase.from("warehouses").delete().eq("warehouse_id", id);
    }

    var UNITS = ["pcs", "kg", "boxes"];

    // Creates the order header, then its line items, then the initial
    // status_log entry — three inserts that together make one order.
    // If any step fails partway through, the error is surfaced as-is;
    // the order row itself isn't rolled back automatically (no
    // multi-table transaction available from the browser client), but
    // an order with zero items is harmless and easy to spot/clean up
    // in Order Tracker if this ever happens.
    function createOrder(supabase, values) {
        return supabase.from("orders").insert({
            customer_id: values.customerId,
            requested_date: values.requestedDate || null,
            notes: values.notes || "",
            status: "Placed",
            placed_by: values.placedBy
        }).select().single().then(function (orderResult) {
            if (orderResult.error) return orderResult;
            var orderId = orderResult.data.order_id;
            var itemRows = values.items.map(function (it) {
                return { order_id: orderId, item: it.item, qty: it.qty, unit: it.unit };
            });
            return supabase.from("order_items").insert(itemRows).then(function (itemsResult) {
                if (itemsResult.error) return itemsResult;
                return supabase.from("status_log").insert({
                    order_id: orderId, status: "Placed", updated_by: values.placedBy, note: ""
                }).then(function (logResult) {
                    if (logResult.error) return logResult;
                    return { data: { order_id: orderId }, error: null };
                });
            });
        });
    }

    var ACTIVE_STATUSES = ["Placed", "Confirmed", "In Production", "Dispatched"];
    var ALL_STATUSES = ACTIVE_STATUSES.concat(["Delivered"]);

    // Who can move an order out of each status, and to which
    // next status(es). Some statuses have more than one valid next
    // step — e.g. a Confirmed order can go to production, or
    // straight to Dispatched if it's already in stock.
    var STATUS_TRANSITIONS = {
        "Placed": [
            { next: "Confirmed", roles: ["Sales Coordinator", "Management", "Admin"], label: "Confirm Order" }
        ],
        "Confirmed": [
            { next: "In Production", roles: ["Factory", "Admin"], label: "Send to Production" },
            { next: "Dispatched", roles: ["Factory", "Admin"], label: "Dispatch (already in stock)" }
        ],
        "In Production": [
            { next: "Dispatched", roles: ["Factory", "Admin"], label: "Mark Dispatched" }
        ],
        "Dispatched": [
            { next: "Delivered", roles: ["Factory", "Sales Coordinator", "Admin"], label: "Mark Delivered" }
        ]
    };

    // Every active (non-Delivered) order, oldest first, with customer
    // and item info joined in. Used by Update Status — Order Tracker
    // (built separately) covers the full history including Delivered.
    function fetchActiveOrders(supabase) {
        return supabase.from("orders")
            .select("*, customers(name, region, rsm), order_items(item, qty, unit)")
            .neq("status", "Delivered")
            .order("placed_at", { ascending: true })
            .then(function (r) {
                var rows = r.data || [];
                return rows.map(function (row) {
                    var cust = row.customers || {};
                    var items = row.order_items || [];
                    var itemsSummary = items.map(function (it) {
                        return it.item + " (" + it.qty + " " + it.unit + ")";
                    }).join(", ");
                    return {
                        order_id: row.order_id,
                        customer_name: cust.name,
                        region: cust.region,
                        rsm: cust.rsm,
                        items_summary: itemsSummary,
                        status: row.status,
                        requested_date: row.requested_date,
                        expected_delivery_date: row.expected_delivery_date,
                        placed_by: row.placed_by,
                        placed_at: row.placed_at
                    };
                });
            });
    }

    // Factory (or Admin) commits an expected delivery date on an
    // active order — separate from the customer's originally
    // requested date. Uses the same "orders" UPDATE permission
    // Factory already has for status changes, so no new RLS policy
    // is needed for this.
    function updateExpectedDeliveryDate(supabase, orderId, date) {
        return supabase.from("orders").update({ expected_delivery_date: date || null }).eq("order_id", orderId);
    }

    function updateOrderStatus(supabase, orderId, newStatus, updatedBy, note) {
        return supabase.from("orders").update({ status: newStatus }).eq("order_id", orderId)
            .then(function (updateResult) {
                if (updateResult.error) return updateResult;
                return supabase.from("status_log").insert({
                    order_id: orderId, status: newStatus, updated_by: updatedBy, note: note || ""
                });
            });
    }

    // Every order regardless of status (including Delivered) — the
    // full history, as opposed to fetchActiveOrders which is
    // Update Status's "current queue" view. Same RLS applies, so a
    // Regional Sales Person automatically only sees their own
    // region's orders here too, with no extra filtering code needed.
    function fetchAllOrders(supabase) {
        return supabase.from("orders")
            .select("*, customers(name, region, rsm), order_items(item, qty, unit)")
            .order("placed_at", { ascending: false })
            .then(function (r) {
                var rows = r.data || [];
                return rows.map(function (row) {
                    var cust = row.customers || {};
                    var items = row.order_items || [];
                    var itemsSummary = items.map(function (it) {
                        return it.item + " (" + it.qty + " " + it.unit + ")";
                    }).join(", ");
                    return {
                        order_id: row.order_id,
                        customer_name: cust.name,
                        region: cust.region,
                        rsm: cust.rsm,
                        items_summary: itemsSummary,
                        status: row.status,
                        requested_date: row.requested_date,
                        expected_delivery_date: row.expected_delivery_date,
                        box_count: row.box_count,
                        notes: row.notes,
                        placed_by: row.placed_by,
                        placed_at: row.placed_at
                    };
                });
            });
    }

    function fetchOrderItemsForDetail(supabase, orderId) {
        return supabase.from("order_items").select("*").eq("order_id", orderId)
            .then(function (r) { return r.data || []; });
    }

    function fetchOrderStatusLog(supabase, orderId) {
        return supabase.from("status_log").select("*").eq("order_id", orderId).order("log_id", { ascending: true })
            .then(function (r) { return r.data || []; });
    }

    function LoginScreen(props) {
        var supabase = props.supabase;
        var emailState = useState("");
        var email = emailState[0], setEmail = emailState[1];
        var passwordState = useState("");
        var password = passwordState[0], setPassword = passwordState[1];
        var errorState = useState("");
        var error = errorState[0], setError = errorState[1];
        var loadingState = useState(false);
        var loading = loadingState[0], setLoading = loadingState[1];

        var handleSubmit = function (e) {
            e.preventDefault();
            setError("");
            setLoading(true);
            supabase.auth.signInWithPassword({ email: email, password: password })
                .then(function (result) {
                    setLoading(false);
                    if (result.error) setError(result.error.message);
                });
        };

        return h("div", { className: "login-wrap" },
            h("form", { className: "login-card", onSubmit: handleSubmit },
                h("div", { className: "login-brand" }, "CAROB TECHNOLOGIES"),
                h("h1", { className: "login-title" }, "Jivan LLP Portal"),
                h("p", { className: "login-sub" }, "Order Tracking & Distribution"),
                error ? h("div", { className: "login-error" }, error) : null,
                h("label", { className: "field-label" }, "Email"),
                h("input", {
                    className: "field-input", type: "email", value: email,
                    onChange: function (e) { setEmail(e.target.value); },
                    required: true, autoFocus: true
                }),
                h("label", { className: "field-label" }, "Password"),
                h("input", {
                    className: "field-input", type: "password", value: password,
                    onChange: function (e) { setPassword(e.target.value); },
                    required: true
                }),
                h("button", { className: "btn-primary", type: "submit", disabled: loading },
                    loading ? "Signing in\u2026" : "Sign In"
                )
            )
        );
    }

    function Sidebar(props) {
        var profile = props.profile;
        var activePage = props.activePage;
        var onNavigate = props.onNavigate;
        var onLogout = props.onLogout;

        var visibleItems = NAV_ITEMS.filter(function (item) {
            return !item.roles || item.roles.indexOf(profile.role) !== -1;
        });

        return h("div", { className: "sidebar" },
            h("div", { className: "sidebar-brand" }, "\uD83D\uDCE6 ", h("span", null, "JIVAN LLP")),
            h("div", { className: "sidebar-sub" }, "Order Tracking Portal"),
            h("div", { className: "sidebar-user" },
                h("div", { className: "sidebar-user-name" }, profile.full_name),
                h("div", { className: "sidebar-user-role" }, profile.role),
                (profile.role === "Regional Sales Person")
                    ? h("div", { className: "sidebar-user-region" },
                        profile.region ? ("Region: " + profile.region) : "No region assigned"
                    )
                    : null
            ),
            visibleItems.map(function (item) {
                return h("button", {
                    key: item.key,
                    className: "nav-link" + (activePage === item.key ? " active" : ""),
                    onClick: function () { onNavigate(item.key); }
                }, item.icon + "  " + item.label);
            }),
            h("button", { className: "sidebar-logout", onClick: onLogout }, "Log out")
        );
    }

    function PlaceholderPage(props) {
        return h("div", null,
            h("h1", { className: "page-title" }, props.title),
            h("p", { className: "page-sub" }, props.note),
            h("div", { className: "placeholder-card" },
                h("strong", null, "Coming next"),
                "This screen is being built next \u2014 the login and navigation foundation is confirmed working first."
            )
        );
    }

    // Generic list + add-form for a single master table. Used for
    // Customers, Products, and Warehouses so that logic isn't
    // triplicated across three near-identical components.
    function MasterSection(props) {
        var supabase = props.supabase;
        var title = props.title;
        var columns = props.columns;       // [{ key, label, render?: (item) => string }]
        var fields = props.fields;         // [{ key, label, type: 'text'|'select', options }]
        var fetchFn = props.fetchFn;       // (supabase) => Promise<array>
        var insertFn = props.insertFn;     // (supabase, values) => Promise<{error}>
        var updateFn = props.updateFn;     // (supabase, id, values) => Promise<{error}>
        var deleteFn = props.deleteFn;     // (supabase, id) => Promise<{error, message?}>
        var rowKey = props.rowKey;         // field name unique per row
        // Optional: for sections needing more than plain delete-by-id
        // (e.g. Products, where delete may become deactivate instead).
        var deleteNeedsFullItem = props.deleteNeedsFullItem || false; // if true, deleteFn(supabase, item) instead of deleteFn(supabase, id)
        var isActiveKey = props.isActiveKey || null;   // field name marking a row active/inactive
        var reactivateFn = props.reactivateFn || null; // (supabase, item) => Promise<{error, message?}>

        var initialFormValues = {};
        fields.forEach(function (f) {
            initialFormValues[f.key] = f.type === "select" ? f.options[0] : "";
        });

        var itemsState = useState([]);
        var items = itemsState[0], setItems = itemsState[1];
        var loadingState = useState(true);
        var loading = loadingState[0], setLoading = loadingState[1];
        var formState = useState(initialFormValues);
        var formValues = formState[0], setFormValues = formState[1];
        var submittingState = useState(false);
        var submitting = submittingState[0], setSubmitting = submittingState[1];
        var errorState = useState("");
        var error = errorState[0], setError = errorState[1];
        var successState = useState("");
        var success = successState[0], setSuccess = successState[1];
        var editingIdState = useState(null);
        var editingId = editingIdState[0], setEditingId = editingIdState[1];
        var deletingIdState = useState(null);
        var deletingId = deletingIdState[0], setDeletingId = deletingIdState[1];

        var loadItems = useCallback(function () {
            setLoading(true);
            fetchFn(supabase).then(function (data) {
                setItems(data);
                setLoading(false);
            });
        }, [supabase]);

        useEffect(function () { loadItems(); }, [loadItems]);

        var handleFieldChange = function (key, value) {
            setFormValues(function (prev) {
                var next = {};
                for (var k in prev) next[k] = prev[k];
                next[key] = value;
                return next;
            });
        };

        var startEdit = function (item) {
            var values = {};
            fields.forEach(function (f) { values[f.key] = item[f.key]; });
            setFormValues(values);
            setEditingId(item[rowKey]);
            setError("");
            setSuccess("");
        };

        var cancelEdit = function () {
            setEditingId(null);
            setFormValues(initialFormValues);
            setError("");
            setSuccess("");
        };

        var handleDelete = function (item) {
            var itemLabel = item[fields[0].key];
            var confirmed = window.confirm("Delete \"" + itemLabel + "\"? This can't be undone if unused elsewhere.");
            if (!confirmed) return;
            setDeletingId(item[rowKey]);
            setError("");
            var action = deleteNeedsFullItem ? deleteFn(supabase, item) : deleteFn(supabase, item[rowKey]);
            action.then(function (result) {
                setDeletingId(null);
                if (result.error) {
                    setError(friendlyErrorMessage(result.error, itemLabel));
                } else {
                    setSuccess(result.message || "Deleted.");
                    loadItems();
                }
            });
        };

        var handleReactivate = function (item) {
            setDeletingId(item[rowKey]);
            setError("");
            reactivateFn(supabase, item).then(function (result) {
                setDeletingId(null);
                if (result.error) {
                    setError(friendlyErrorMessage(result.error, item[fields[0].key]));
                } else {
                    setSuccess(result.message || "Reactivated.");
                    loadItems();
                }
            });
        };

        var handleSubmit = function (e) {
            e.preventDefault();
            var missing = fields.filter(function (f) { return !formValues[f.key]; });
            if (missing.length > 0) {
                setError("Fill in: " + missing.map(function (f) { return f.label; }).join(", "));
                setSuccess("");
                return;
            }
            setSubmitting(true);
            setError("");
            setSuccess("");

            var action = editingId
                ? updateFn(supabase, editingId, formValues)
                : insertFn(supabase, formValues);

            action.then(function (result) {
                setSubmitting(false);
                if (result.error) {
                    setError(friendlyErrorMessage(result.error, formValues[fields[0].key]));
                } else {
                    setSuccess(editingId ? "Updated." : "Added.");
                    setFormValues(initialFormValues);
                    setEditingId(null);
                    loadItems();
                }
            });
        };

        var tableContent;
        if (loading) {
            tableContent = h("p", { className: "muted-text" }, "Loading\u2026");
        } else if (items.length === 0) {
            tableContent = h("p", { className: "muted-text" }, "None added yet.");
        } else {
            tableContent = h("table", { className: "data-table" },
                h("thead", null,
                    h("tr", null,
                        columns.map(function (c) {
                            return h("th", { key: c.key }, c.label);
                        }).concat([h("th", { key: "__actions" }, "")])
                    )
                ),
                h("tbody", null, items.map(function (item) {
                    var isInactive = isActiveKey && item[isActiveKey] === false;
                    var busy = deletingId === item[rowKey];
                    return h("tr", { key: item[rowKey], style: isInactive ? { opacity: 0.6 } : null },
                        columns.map(function (c) {
                            var content = c.render ? c.render(item) : (item[c.key] == null ? "" : String(item[c.key]));
                            return h("td", { key: c.key }, content);
                        }).concat([
                            h("td", { key: "__actions", className: "actions-cell" },
                                h("button", {
                                    type: "button", className: "link-btn",
                                    onClick: function () { startEdit(item); }
                                }, "Edit"),
                                (isInactive && reactivateFn)
                                    ? h("button", {
                                        type: "button", className: "link-btn",
                                        disabled: busy,
                                        onClick: function () { handleReactivate(item); }
                                    }, busy ? "Reactivating\u2026" : "Reactivate")
                                    : h("button", {
                                        type: "button", className: "link-btn link-btn-danger",
                                        disabled: busy,
                                        onClick: function () { handleDelete(item); }
                                    }, busy ? "Deleting\u2026" : "Delete")
                            )
                        ])
                    );
                }))
            );
        }

        return h("div", { className: "master-section" },
            h("h2", { className: "section-title" }, title),
            tableContent,
            h("form", { className: "inline-form", onSubmit: handleSubmit },
                fields.map(function (f) {
                    if (f.type === "select") {
                        return h("select", {
                            key: f.key, className: "field-input-sm",
                            value: formValues[f.key],
                            onChange: function (e) { handleFieldChange(f.key, e.target.value); }
                        }, f.options.map(function (opt) {
                            return h("option", { key: opt, value: opt }, opt);
                        }));
                    }
                    return h("input", {
                        key: f.key, className: "field-input-sm", type: "text",
                        placeholder: f.label, value: formValues[f.key],
                        onChange: function (e) { handleFieldChange(f.key, e.target.value); }
                    });
                }),
                h("button", { className: "btn-small", type: "submit", disabled: submitting },
                    submitting ? (editingId ? "Saving\u2026" : "Adding\u2026") : (editingId ? "Save" : "Add")
                ),
                editingId ? h("button", {
                    type: "button", className: "btn-small btn-secondary", onClick: cancelEdit
                }, "Cancel") : null,
                error ? h("span", { className: "form-error" }, error) : null,
                success ? h("span", { className: "form-success" }, success) : null
            )
        );
    }

    function AdminPage(props) {
        var supabase = props.supabase;
        return h("div", null,
            h("h1", { className: "page-title" }, "Admin"),
            h("p", { className: "page-sub" }, "Manage customers, products, warehouses, and users."),

            h(MasterSection, {
                supabase: supabase, title: "Customers", rowKey: "customer_id",
                columns: [
                    { key: "name", label: "Name" },
                    { key: "region", label: "Region" },
                    { key: "rsm", label: "RSM" }
                ],
                fields: [
                    { key: "name", label: "Customer name", type: "text" },
                    { key: "region", label: "Region", type: "select", options: REGIONS },
                    { key: "rsm", label: "RSM name", type: "text" }
                ],
                fetchFn: fetchCustomers, insertFn: insertCustomer,
                updateFn: updateCustomer, deleteFn: deleteCustomer
            }),

            h(MasterSection, {
                supabase: supabase, title: "Products", rowKey: "product_id",
                columns: [
                    { key: "name", label: "Name" },
                    {
                        key: "is_active", label: "Status",
                        render: function (item) {
                            return item.is_active
                                ? h("span", { className: "status-badge status-delivered" }, "Active")
                                : h("span", { className: "status-badge status-placed" }, "Inactive");
                        }
                    }
                ],
                fields: [{ key: "name", label: "Product name", type: "text" }],
                fetchFn: fetchProducts, insertFn: insertProduct,
                updateFn: updateProduct, deleteFn: deleteOrDeactivateProduct,
                deleteNeedsFullItem: true, isActiveKey: "is_active", reactivateFn: reactivateProduct
            }),

            h(MasterSection, {
                supabase: supabase, title: "Warehouses", rowKey: "warehouse_id",
                columns: [
                    { key: "name", label: "Name" },
                    { key: "region", label: "Region" }
                ],
                fields: [
                    { key: "name", label: "Warehouse name", type: "text" },
                    { key: "region", label: "Region", type: "select", options: REGIONS }
                ],
                fetchFn: fetchWarehouses, insertFn: insertWarehouse,
                updateFn: updateWarehouse, deleteFn: deleteWarehouse
            }),

            h("div", { className: "master-section" },
                h("h2", { className: "section-title" }, "Users"),
                h("div", { className: "placeholder-card" },
                    h("strong", null, "Needs a backend piece first"),
                    "Creating a new login requires Supabase's admin API, which needs the service_role key \u2014 " +
                    "that key can never be used in browser code, since it bypasses all the RLS security this app " +
                    "relies on. This needs a small server-side function (a Supabase Edge Function) before it can " +
                    "be built here. Until then, add users via Supabase Dashboard \u2192 Authentication \u2192 Users, " +
                    "then insert their profile row manually (same steps used for the first Admin account)."
                )
            )
        );
    }

    function OrderEntry(props) {
        var supabase = props.supabase;
        var profile = props.profile;

        var customersState = useState([]);
        var customers = customersState[0], setCustomers = customersState[1];
        var productsState = useState([]);
        var products = productsState[0], setProducts = productsState[1];
        var loadingMastersState = useState(true);
        var loadingMasters = loadingMastersState[0], setLoadingMasters = loadingMastersState[1];

        var customerIdState = useState("");
        var customerId = customerIdState[0], setCustomerId = customerIdState[1];
        var requestedDateState = useState("");
        var requestedDate = requestedDateState[0], setRequestedDate = requestedDateState[1];
        var notesState = useState("");
        var notes = notesState[0], setNotes = notesState[1];

        var cartState = useState([]);
        var cart = cartState[0], setCart = cartState[1];
        var draftProductState = useState("");
        var draftProduct = draftProductState[0], setDraftProduct = draftProductState[1];
        var draftQtyState = useState(100);
        var draftQty = draftQtyState[0], setDraftQty = draftQtyState[1];
        var draftUnitState = useState(UNITS[0]);
        var draftUnit = draftUnitState[0], setDraftUnit = draftUnitState[1];

        var submittingState = useState(false);
        var submitting = submittingState[0], setSubmitting = submittingState[1];
        var errorState = useState("");
        var error = errorState[0], setError = errorState[1];
        var successState = useState("");
        var success = successState[0], setSuccess = successState[1];

        useEffect(function () {
            setLoadingMasters(true);
            Promise.all([fetchCustomers(supabase), fetchActiveProducts(supabase)]).then(function (results) {
                var custs = results[0], prods = results[1];
                setCustomers(custs);
                setProducts(prods);
                if (custs.length > 0) setCustomerId(String(custs[0].customer_id));
                if (prods.length > 0) setDraftProduct(prods[0].name);
                setLoadingMasters(false);
            });
        }, [supabase]);

        var addToCart = function () {
            if (!draftProduct || !draftQty || Number(draftQty) <= 0) {
                setError("Pick a product and a quantity greater than 0.");
                return;
            }
            setCart(function (prev) {
                return prev.concat([{ item: draftProduct, qty: Number(draftQty), unit: draftUnit }]);
            });
            setError("");
        };

        var removeFromCart = function (index) {
            setCart(function (prev) {
                return prev.filter(function (_, i) { return i !== index; });
            });
        };

        var handleSubmit = function (e) {
            e.preventDefault();
            if (!customerId) { setError("Select a customer."); return; }
            if (cart.length === 0) { setError("Add at least one item to the order."); return; }
            setSubmitting(true);
            setError("");
            setSuccess("");
            createOrder(supabase, {
                customerId: customerId, items: cart, requestedDate: requestedDate,
                notes: notes, placedBy: profile.full_name
            }).then(function (result) {
                setSubmitting(false);
                if (result.error) {
                    setError(result.error.message);
                } else {
                    setSuccess("Order #" + result.data.order_id + " placed with " + cart.length + " item(s).");
                    setCart([]);
                    setNotes("");
                    setRequestedDate("");
                }
            });
        };

        if (loadingMasters) {
            return h("div", null,
                h("h1", { className: "page-title" }, "New Order Entry"),
                h("p", { className: "muted-text" }, "Loading customers and products\u2026")
            );
        }

        if (customers.length === 0 || products.length === 0) {
            return h("div", null,
                h("h1", { className: "page-title" }, "New Order Entry"),
                h("div", { className: "placeholder-card" },
                    h("strong", null, "Add customers and products first"),
                    "Order Entry needs at least one customer and one product \u2014 add them in Admin first."
                )
            );
        }

        var selectedCustomer = customers.filter(function (c) {
            return String(c.customer_id) === String(customerId);
        })[0];

        return h("div", null,
            h("h1", { className: "page-title" }, "New Order Entry"),
            h("p", { className: "page-sub" }, "Create a multi-item order for a customer."),

            h("div", { className: "master-section" },
                h("label", { className: "field-label" }, "Customer"),
                h("select", {
                    className: "field-input", value: customerId,
                    onChange: function (e) { setCustomerId(e.target.value); }
                }, customers.map(function (c) {
                    return h("option", { key: c.customer_id, value: String(c.customer_id) },
                        c.name + " (" + c.region + ")");
                })),
                selectedCustomer ? h("p", { className: "muted-text" }, "RSM: " + selectedCustomer.rsm) : null,

                h("h2", { className: "section-title" }, "Add items"),
                h("div", { className: "inline-form" },
                    h("select", {
                        className: "field-input-sm", value: draftProduct,
                        onChange: function (e) { setDraftProduct(e.target.value); }
                    }, products.map(function (p) {
                        return h("option", { key: p.product_id, value: p.name }, p.name);
                    })),
                    h("input", {
                        className: "field-input-sm", type: "number", min: 1, value: draftQty,
                        onChange: function (e) { setDraftQty(e.target.value); }
                    }),
                    h("select", {
                        className: "field-input-sm", value: draftUnit,
                        onChange: function (e) { setDraftUnit(e.target.value); }
                    }, UNITS.map(function (u) {
                        return h("option", { key: u, value: u }, u);
                    })),
                    h("button", { type: "button", className: "btn-small", onClick: addToCart }, "+ Add")
                ),

                cart.length > 0
                    ? h("table", { className: "data-table" },
                        h("thead", null, h("tr", null,
                            h("th", null, "Item"), h("th", null, "Qty"), h("th", null, "Unit"), h("th", null, "")
                        )),
                        h("tbody", null, cart.map(function (line, i) {
                            return h("tr", { key: i },
                                h("td", null, line.item),
                                h("td", null, line.qty),
                                h("td", null, line.unit),
                                h("td", { className: "actions-cell" },
                                    h("button", {
                                        type: "button", className: "link-btn link-btn-danger",
                                        onClick: function () { removeFromCart(i); }
                                    }, "Remove")
                                )
                            );
                        }))
                    )
                    : h("p", { className: "muted-text" }, "No items added yet."),

                h("form", { onSubmit: handleSubmit },
                    h("label", { className: "field-label" }, "Requested delivery date"),
                    h("input", {
                        className: "field-input", type: "date", value: requestedDate,
                        onChange: function (e) { setRequestedDate(e.target.value); }
                    }),
                    h("label", { className: "field-label" }, "Notes (optional)"),
                    h("input", {
                        className: "field-input", type: "text", value: notes,
                        onChange: function (e) { setNotes(e.target.value); }
                    }),
                    h("button", { className: "btn-primary", type: "submit", disabled: submitting },
                        submitting ? "Placing order\u2026" : "Submit Order"
                    ),
                    error ? h("div", { className: "login-error" }, error) : null,
                    success ? h("div", { className: "form-success" }, success) : null
                )
            )
        );
    }

    function UpdateStatusPage(props) {
        var supabase = props.supabase;
        var profile = props.profile;

        var ordersState = useState([]);
        var orders = ordersState[0], setOrders = ordersState[1];
        var loadingState = useState(true);
        var loading = loadingState[0], setLoading = loadingState[1];
        var selectedStatusesState = useState([]); // empty = show all
        var selectedStatuses = selectedStatusesState[0], setSelectedStatuses = selectedStatusesState[1];
        var actingIdState = useState(null); // order_id currently being updated, disables its buttons
        var actingId = actingIdState[0], setActingId = actingIdState[1];
        var errorState = useState("");
        var error = errorState[0], setError = errorState[1];
        var dateDraftsState = useState({}); // orderId -> in-progress date input value
        var dateDrafts = dateDraftsState[0], setDateDrafts = dateDraftsState[1];
        var savingDateIdState = useState(null);
        var savingDateId = savingDateIdState[0], setSavingDateId = savingDateIdState[1];

        var loadOrders = useCallback(function () {
            setLoading(true);
            fetchActiveOrders(supabase).then(function (data) {
                setOrders(data);
                setLoading(false);
            });
        }, [supabase]);

        useEffect(function () { loadOrders(); }, [loadOrders]);

        var toggleStatus = function (status) {
            setSelectedStatuses(function (prev) {
                return prev.indexOf(status) === -1
                    ? prev.concat([status])
                    : prev.filter(function (s) { return s !== status; });
            });
        };

        var handleDateChange = function (orderId, value) {
            setDateDrafts(function (prev) {
                var next = {};
                for (var k in prev) next[k] = prev[k];
                next[orderId] = value;
                return next;
            });
        };

        var handleSaveDate = function (order) {
            var value = dateDrafts.hasOwnProperty(order.order_id)
                ? dateDrafts[order.order_id]
                : (order.expected_delivery_date || "");
            setSavingDateId(order.order_id);
            setError("");
            updateExpectedDeliveryDate(supabase, order.order_id, value).then(function (result) {
                setSavingDateId(null);
                if (result.error) {
                    setError(friendlyErrorMessage(result.error, "Order #" + order.order_id));
                } else {
                    loadOrders();
                }
            });
        };

        var handleAction = function (order, transition) {
            setActingId(order.order_id);
            setError("");
            updateOrderStatus(supabase, order.order_id, transition.next, profile.full_name, "")
                .then(function (result) {
                    setActingId(null);
                    if (result.error) {
                        setError(result.error.message);
                    } else {
                        loadOrders();
                    }
                });
        };

        var visibleOrders = selectedStatuses.length === 0
            ? orders
            : orders.filter(function (o) { return selectedStatuses.indexOf(o.status) !== -1; });

        if (profile.role === "Regional Sales Person" && !profile.region) {
            return h("div", null,
                h("h1", { className: "page-title" }, "Update Status"),
                h("div", { className: "placeholder-card" },
                    h("strong", null, "No region assigned yet"),
                    "Your account isn't assigned to a region, so no orders can be shown. Ask an Admin to set your region."
                )
            );
        }

        return h("div", null,
            h("h1", { className: "page-title" }, "Update Status"),
            h("p", { className: "page-sub" },
                "Every active order, oldest first. Leave all boxes unchecked to see everything."
            ),

            h("div", { className: "inline-form", style: { marginBottom: "16px" } },
                ACTIVE_STATUSES.map(function (s) {
                    return h("label", { key: s, className: "checkbox-label" },
                        h("input", {
                            type: "checkbox",
                            checked: selectedStatuses.indexOf(s) !== -1,
                            onChange: function () { toggleStatus(s); }
                        }),
                        " " + s
                    );
                })
            ),

            error ? h("div", { className: "login-error" }, error) : null,

            loading
                ? h("p", { className: "muted-text" }, "Loading\u2026")
                : visibleOrders.length === 0
                    ? h("div", { className: "placeholder-card" }, "No orders match right now.")
                    : visibleOrders.map(function (order) {
                        var transitions = STATUS_TRANSITIONS[order.status] || [];
                        var actionable = transitions.filter(function (t) {
                            return t.roles.indexOf(profile.role) !== -1;
                        });
                        var viewOnlyRoles = transitions.length > 0 && actionable.length === 0
                            ? Array.prototype.concat.apply([], transitions.map(function (t) { return t.roles; }))
                                .filter(function (r, i, arr) { return arr.indexOf(r) === i; })
                            : null;

                        return h("div", { key: order.order_id, className: "order-card" },
                            h("div", { className: "order-card-main" },
                                h("div", { className: "order-card-title" },
                                    "Order #" + order.order_id + " \u2014 " + order.customer_name
                                ),
                                h("div", { className: "muted-text" },
                                    order.items_summary + " \u00b7 Requested " + (order.requested_date || "\u2014") +
                                    " \u00b7 Expected delivery: " + (order.expected_delivery_date || "not set")
                                ),
                                h("span", { className: "status-badge status-" + order.status.replace(/\s+/g, "-").toLowerCase() },
                                    order.status
                                ),
                                (profile.role === "Factory" || profile.role === "Admin")
                                    ? h("div", { className: "inline-form", style: { marginTop: "8px" } },
                                        h("input", {
                                            type: "date", className: "field-input-sm",
                                            value: dateDrafts.hasOwnProperty(order.order_id)
                                                ? dateDrafts[order.order_id]
                                                : (order.expected_delivery_date || ""),
                                            onChange: function (e) { handleDateChange(order.order_id, e.target.value); }
                                        }),
                                        h("button", {
                                            type: "button", className: "btn-small",
                                            disabled: savingDateId === order.order_id,
                                            onClick: function () { handleSaveDate(order); }
                                        }, savingDateId === order.order_id ? "Saving\u2026" : "Save Date")
                                    )
                                    : null
                            ),
                            h("div", { className: "order-card-actions" },
                                actionable.length > 0
                                    ? actionable.map(function (t) {
                                        return h("button", {
                                            key: t.next, type: "button", className: "btn-small",
                                            disabled: actingId === order.order_id,
                                            onClick: function () { handleAction(order, t); }
                                        }, actingId === order.order_id ? "Updating\u2026" : t.label);
                                    })
                                    : viewOnlyRoles
                                        ? h("span", { className: "muted-text" },
                                            "Done by: " + viewOnlyRoles.join(", "))
                                        : null
                            )
                        );
                    })
        );
    }

    function OrderTrackerPage(props) {
        var supabase = props.supabase;
        var profile = props.profile;

        var ordersState = useState([]);
        var orders = ordersState[0], setOrders = ordersState[1];
        var loadingState = useState(true);
        var loading = loadingState[0], setLoading = loadingState[1];

        var customerFilterState = useState("");
        var customerFilter = customerFilterState[0], setCustomerFilter = customerFilterState[1];
        var regionFilterState = useState("");
        var regionFilter = regionFilterState[0], setRegionFilter = regionFilterState[1];
        var statusFilterState = useState([]);
        var statusFilter = statusFilterState[0], setStatusFilter = statusFilterState[1];

        var expandedIdState = useState(null);
        var expandedId = expandedIdState[0], setExpandedId = expandedIdState[1];
        var detailCacheState = useState({});
        var detailCache = detailCacheState[0], setDetailCache = detailCacheState[1];

        // Browser-native print (not a PDF library) — every browser can
        // "Save as PDF" from its own print dialog, so this needs zero
        // external dependencies. A CSS class toggled on <body> swaps
        // what's visible only for the print output, leaving the normal
        // on-screen view completely unaffected.
        useEffect(function () {
            var handleAfterPrint = function () {
                document.body.classList.remove("printing-mode");
            };
            window.addEventListener("afterprint", handleAfterPrint);
            return function () { window.removeEventListener("afterprint", handleAfterPrint); };
        }, []);

        var handlePrint = function () {
            document.body.classList.add("printing-mode");
            window.print();
        };

        var loadOrders = useCallback(function () {
            setLoading(true);
            fetchAllOrders(supabase).then(function (data) {
                setOrders(data);
                setLoading(false);
            });
        }, [supabase]);

        useEffect(function () { loadOrders(); }, [loadOrders]);

        var toggleStatusFilter = function (status) {
            setStatusFilter(function (prev) {
                return prev.indexOf(status) === -1
                    ? prev.concat([status])
                    : prev.filter(function (s) { return s !== status; });
            });
        };

        var toggleExpand = function (order) {
            if (expandedId === order.order_id) {
                setExpandedId(null);
                return;
            }
            setExpandedId(order.order_id);
            if (!detailCache[order.order_id]) {
                setDetailCache(function (prev) {
                    var next = {};
                    for (var k in prev) next[k] = prev[k];
                    next[order.order_id] = { loading: true };
                    return next;
                });
                Promise.all([
                    fetchOrderItemsForDetail(supabase, order.order_id),
                    fetchOrderStatusLog(supabase, order.order_id)
                ]).then(function (results) {
                    setDetailCache(function (prev) {
                        var next = {};
                        for (var k in prev) next[k] = prev[k];
                        next[order.order_id] = { loading: false, items: results[0], history: results[1] };
                        return next;
                    });
                });
            }
        };

        var customerOptions = [];
        orders.forEach(function (o) {
            if (o.customer_name && customerOptions.indexOf(o.customer_name) === -1) {
                customerOptions.push(o.customer_name);
            }
        });
        customerOptions.sort();

        var filtered = orders.filter(function (o) {
            if (customerFilter && o.customer_name !== customerFilter) return false;
            if (regionFilter && o.region !== regionFilter) return false;
            if (statusFilter.length > 0 && statusFilter.indexOf(o.status) === -1) return false;
            return true;
        });

        return h("div", null,
            h("h1", { className: "page-title" }, "Order Tracker"),
            h("p", { className: "page-sub" }, "Every order, all statuses including Delivered."),

            h("div", { className: "inline-form", style: { marginBottom: "10px" } },
                h("select", {
                    className: "field-input-sm", value: customerFilter,
                    onChange: function (e) { setCustomerFilter(e.target.value); }
                }, [h("option", { key: "", value: "" }, "All customers")].concat(
                    customerOptions.map(function (c) { return h("option", { key: c, value: c }, c); })
                )),
                h("select", {
                    className: "field-input-sm", value: regionFilter,
                    onChange: function (e) { setRegionFilter(e.target.value); }
                }, [h("option", { key: "", value: "" }, "All regions")].concat(
                    REGIONS.map(function (r) { return h("option", { key: r, value: r }, r); })
                ))
            ),
            h("div", { className: "inline-form", style: { marginBottom: "16px" } },
                ALL_STATUSES.map(function (s) {
                    return h("label", { key: s, className: "checkbox-label" },
                        h("input", {
                            type: "checkbox",
                            checked: statusFilter.indexOf(s) !== -1,
                            onChange: function () { toggleStatusFilter(s); }
                        }),
                        " " + s
                    );
                })
            ),

            loading
                ? h("p", { className: "muted-text" }, "Loading\u2026")
                : filtered.length === 0
                    ? h("div", { className: "placeholder-card" }, "No orders match these filters.")
                    : h("div", null,
                        h("p", { className: "muted-text" }, filtered.length + " order(s)"),
                        filtered.map(function (order) {
                            var isExpanded = expandedId === order.order_id;
                            var detail = detailCache[order.order_id];
                            return h("div", { key: order.order_id },
                                h("div", {
                                    className: "order-card", style: { cursor: "pointer" },
                                    onClick: function () { toggleExpand(order); }
                                },
                                    h("div", { className: "order-card-main" },
                                        h("div", { className: "order-card-title" },
                                            "Order #" + order.order_id + " \u2014 " + order.customer_name
                                        ),
                                        h("div", { className: "muted-text" }, order.items_summary),
                                        h("div", { className: "muted-text" },
                                            "Requested: " + (order.requested_date || "\u2014") +
                                            " \u00b7 Expected delivery: " + (order.expected_delivery_date || "\u2014")
                                        ),
                                        h("span", {
                                            className: "status-badge status-" +
                                                order.status.replace(/\s+/g, "-").toLowerCase()
                                        }, order.status)
                                    ),
                                    h("div", { className: "order-card-actions" },
                                        h("span", { className: "link-btn" }, isExpanded ? "Hide detail" : "View detail")
                                    )
                                ),
                                isExpanded
                                    ? h("div", { className: "master-section", style: { marginTop: "-6px", marginBottom: "14px" } },
                                        (!detail || detail.loading)
                                            ? h("p", { className: "muted-text" }, "Loading detail\u2026")
                                            : h("div", null,
                                                h("h2", { className: "section-title" }, "Line items"),
                                                detail.items.length === 0
                                                    ? h("p", { className: "muted-text" }, "No items.")
                                                    : h("table", { className: "data-table" },
                                                        h("thead", null, h("tr", null,
                                                            h("th", null, "Item"), h("th", null, "Qty"), h("th", null, "Unit")
                                                        )),
                                                        h("tbody", null, detail.items.map(function (it, i) {
                                                            return h("tr", { key: i },
                                                                h("td", null, it.item), h("td", null, it.qty), h("td", null, it.unit)
                                                            );
                                                        }))
                                                    ),
                                                h("h2", { className: "section-title", style: { marginTop: "16px" } }, "Status history"),
                                                detail.history.length === 0
                                                    ? h("p", { className: "muted-text" }, "No history.")
                                                    : h("table", { className: "data-table" },
                                                        h("thead", null, h("tr", null,
                                                            h("th", null, "Status"), h("th", null, "By"),
                                                            h("th", null, "When"), h("th", null, "Note")
                                                        )),
                                                        h("tbody", null, detail.history.map(function (entry) {
                                                            return h("tr", { key: entry.log_id },
                                                                h("td", null, entry.status),
                                                                h("td", null, entry.updated_by),
                                                                h("td", null, entry.updated_at),
                                                                h("td", null, entry.note || "")
                                                            );
                                                        }))
                                                    ),
                                                (profile.role === "Factory" || profile.role === "Admin")
                                                    ? h("div", { style: { marginTop: "16px" } },
                                                        h("button", {
                                                            type: "button", className: "btn-small",
                                                            onClick: handlePrint
                                                        }, "\uD83D\uDDA8\uFE0F Print Order"),
                                                        h("p", { className: "muted-text", style: { marginTop: "6px" } },
                                                            "Opens your browser's print dialog \u2014 choose \"Save as PDF\" there to get a PDF instead of a physical printout."
                                                        ),
                                                        // Rendered via portal into #print-root (outside
                                                        // .app-shell), not inline here — see
                                                        // renderPrintPortal's comment for why.
                                                        renderPrintPortal(
                                                            h("div", { className: "print-sheet" },
                                                                h("h1", null, "Order #" + order.order_id),
                                                                h("p", null, "Carob Technologies \u2014 Jivan LLP"),
                                                                h("table", { className: "print-info-table" },
                                                                    h("tbody", null,
                                                                        h("tr", null, h("td", null, "Customer"), h("td", null, order.customer_name)),
                                                                        h("tr", null, h("td", null, "Region"), h("td", null, order.region)),
                                                                        h("tr", null, h("td", null, "RSM"), h("td", null, order.rsm || "\u2014")),
                                                                        h("tr", null, h("td", null, "Status"), h("td", null, order.status)),
                                                                        h("tr", null, h("td", null, "Requested date"), h("td", null, order.requested_date || "\u2014")),
                                                                        h("tr", null, h("td", null, "Expected delivery"), h("td", null, order.expected_delivery_date || "\u2014")),
                                                                        order.box_count
                                                                            ? h("tr", null, h("td", null, "Box count"), h("td", null, String(order.box_count)))
                                                                            : null,
                                                                        h("tr", null, h("td", null, "Placed by"), h("td", null, order.placed_by))
                                                                    )
                                                                ),
                                                                h("h3", null, "Items"),
                                                                h("table", { className: "print-items-table" },
                                                                    h("thead", null, h("tr", null,
                                                                        h("th", null, "Item"), h("th", null, "Qty"), h("th", null, "Unit")
                                                                    )),
                                                                    h("tbody", null, detail.items.map(function (it, i) {
                                                                        return h("tr", { key: i },
                                                                            h("td", null, it.item), h("td", null, it.qty), h("td", null, it.unit)
                                                                        );
                                                                    }))
                                                                ),
                                                                order.notes ? h("p", null, h("strong", null, "Notes: "), order.notes) : null,
                                                                h("div", { className: "print-signoff" },
                                                                    h("p", null, "Received by: ________________________"),
                                                                    h("p", null, "Date: ________________________")
                                                                )
                                                            )
                                                        )
                                                    )
                                                    : null
                                            )
                                    )
                                    : null
                            );
                        })
                    )
        );
    }

    function App(props) {
        var supabase = props.supabase;
        var sessionState = useState(undefined); // undefined = still checking
        var session = sessionState[0], setSession = sessionState[1];
        var profileState = useState(null);
        var profile = profileState[0], setProfile = profileState[1];
        var profileErrorState = useState("");
        var profileError = profileErrorState[0], setProfileError = profileErrorState[1];
        var activePageState = useState("order-tracker");
        var activePage = activePageState[0], setActivePage = activePageState[1];

        useEffect(function () {
            supabase.auth.getSession().then(function (result) {
                setSession(result.data.session);
            });
            var sub = supabase.auth.onAuthStateChange(function (_event, newSession) {
                setSession(newSession);
            });
            return function () { sub.data.subscription.unsubscribe(); };
        }, []);

        var loadProfile = useCallback(function (userId) {
            setProfileError("");
            supabase.from("user_profiles").select("*").eq("user_id", userId).single()
                .then(function (result) {
                    if (result.error) {
                        setProfileError("Signed in, but no profile found for this account. Ask an Admin to add you in Manage Users.");
                        setProfile(null);
                    } else {
                        setProfile(result.data);
                    }
                });
        }, []);

        useEffect(function () {
            if (session === undefined) return;
            if (session === null) { setProfile(null); return; }
            loadProfile(session.user.id);
        }, [session, loadProfile]);

        var handleLogout = function () { supabase.auth.signOut(); };

        if (session === undefined) {
            return h("div", { className: "loading-wrap" }, "Loading\u2026");
        }
        if (!session) {
            return h(LoginScreen, { supabase: supabase });
        }
        if (profileError) {
            return h("div", { className: "loading-wrap", style: { flexDirection: "column", gap: "12px" } },
                h("div", null, profileError),
                h("button", {
                    className: "sidebar-logout",
                    style: { color: "var(--navy)", borderColor: "var(--navy)" },
                    onClick: handleLogout
                }, "Log out")
            );
        }
        if (!profile) {
            return h("div", { className: "loading-wrap" }, "Loading your profile\u2026");
        }

        var meta = PAGE_META[activePage];
        var pageContent;
        if (activePage === "admin") {
            pageContent = h(AdminPage, { supabase: supabase });
        } else if (activePage === "order-entry") {
            pageContent = h(OrderEntry, { supabase: supabase, profile: profile });
        } else if (activePage === "update-status") {
            pageContent = h(UpdateStatusPage, { supabase: supabase, profile: profile });
        } else if (activePage === "order-tracker") {
            pageContent = h(OrderTrackerPage, { supabase: supabase, profile: profile });
        } else {
            pageContent = h(PlaceholderPage, { title: meta.title, note: meta.note });
        }

        return h("div", { className: "app-shell" },
            h(Sidebar, {
                profile: profile, activePage: activePage,
                onNavigate: setActivePage, onLogout: handleLogout
            }),
            h("div", { className: "main-area" }, pageContent)
        );
    }

    return {
        App: App,
        LoginScreen: LoginScreen,
        Sidebar: Sidebar,
        PlaceholderPage: PlaceholderPage,
        MasterSection: MasterSection,
        AdminPage: AdminPage,
        OrderEntry: OrderEntry,
        createOrder: createOrder,
        UNITS: UNITS,
        UpdateStatusPage: UpdateStatusPage,
        fetchActiveOrders: fetchActiveOrders,
        updateExpectedDeliveryDate: updateExpectedDeliveryDate,
        updateOrderStatus: updateOrderStatus,
        STATUS_TRANSITIONS: STATUS_TRANSITIONS,
        ACTIVE_STATUSES: ACTIVE_STATUSES,
        ALL_STATUSES: ALL_STATUSES,
        OrderTrackerPage: OrderTrackerPage,
        renderPrintPortal: renderPrintPortal,
        fetchAllOrders: fetchAllOrders,
        fetchOrderItemsForDetail: fetchOrderItemsForDetail,
        fetchOrderStatusLog: fetchOrderStatusLog,
        NAV_ITEMS: NAV_ITEMS,
        PAGE_META: PAGE_META,
        REGIONS: REGIONS,
        fetchCustomers: fetchCustomers,
        friendlyErrorMessage: friendlyErrorMessage,
        insertCustomer: insertCustomer,
        updateCustomer: updateCustomer,
        deleteCustomer: deleteCustomer,
        fetchProducts: fetchProducts,
        fetchActiveProducts: fetchActiveProducts,
        insertProduct: insertProduct,
        updateProduct: updateProduct,
        deleteOrDeactivateProduct: deleteOrDeactivateProduct,
        reactivateProduct: reactivateProduct,
        fetchWarehouses: fetchWarehouses,
        insertWarehouse: insertWarehouse,
        updateWarehouse: updateWarehouse,
        deleteWarehouse: deleteWarehouse
    };
});
