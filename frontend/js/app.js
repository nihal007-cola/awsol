// ==============================================================
// ERP SNEAHA CREATIONS - COMPLETE APP.JS
// ==============================================================
// VERSION: 3.0.0 - CLEAN
// WORKFLOW: 10-STAGE PRODUCTION MANAGEMENT SYSTEM
// ==============================================================

// ==============================================================
// SECTION 1: GLOBAL STATE VARIABLES
// ==============================================================

let partiesData = [];
let currentUserRole = "viewer";
let rmInventoryData = [];
let reportDataCache = {};
let rmSupplierCb = null;
let storedBOMState = null;

// ==============================================================
// SECTION 2: ERP STATE OBJECT
// ==============================================================

const ERP_STATE = {
    currentFGOrderSerial: null,
    gridData: [],
    bomCurrentFGKey: null,
    bomItemsData: [],
    bomOrderId: null,
    bomGridData: [],
    bomSizes: [],
    supplierOptions: [],
    rmOrdersData: [],
    selectedGroups: new Set(),
    currentPOToken: null,
    grnData: [],
    shortfallData: [],
    issueRMData: [],
    buyerName: '',
    buyerGST: '',
    buyerOrderNo: '',
    orderDate: '',
    deliveryDate: '',
    leadTime: 0,
    noOfFG: 0,
    isBomModalOpen: false,
    reportData: { buyer_status: [], rm_stock: [], rm_ordered: [] },
    reportFilters: { suppliers: [], fgKeys: [] },
    currentSupplierItems: [],
    groupMap: {},
    groupItemsMap: {},
    currentGRNData: null,
    isBOMAssignmentOpen: false,
    lastOrderId: null
};

// ==============================================================
// SECTION 3: API CLIENT
// ==============================================================

const API = {
    baseUrl: '',

    async call(endpoint, method = 'GET', data = null) {
        const url = `${this.baseUrl}${endpoint}`;
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
        };
        if (data) {
            options.body = JSON.stringify(data);
        }
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    getBuyers() { return this.call('/master/buyers'); },
    getRMSuppliers() { return this.call('/master/suppliers'); },
    addBuyer(data) { return this.call('/master/buyers', 'POST', data); },
    addRMSupplier(data) { return this.call('/master/suppliers', 'POST', data); },

    generateFGSerial() { return this.call('/buyer-order/fg-serial'); },
    generateOrderGrid(data) { return this.call('/buyer-order/generate-grid', 'POST', data); },
    saveOrder(data) { return this.call('/buyer-order/save', 'POST', data); },
    getBuyerOrders(showCancelled) {
        const url = showCancelled ? '/buyer-order/orders?show_cancelled=true' : '/buyer-order/orders';
        return this.call(url);
    },
    cancelBuyerOrder(orderId) { return this.call('/buyer-order/cancel', 'POST', { buyer_order_id: orderId }); },
    processToBom(orderId) { return this.call('/buyer-order/process-to-bom', 'POST', { buyer_order_id: orderId }); },
    getOrderGrid(orderId) { return this.call(`/buyer-order/grid/${orderId}`); },
    printBuyerOrder(orderId) { return this.call(`/buyer-order/print/${orderId}`); },

    getBOMOrders() { return this.call('/bom/orders'); },
    getBOMData(fgKey) { return this.call(`/bom/${encodeURIComponent(fgKey)}`); },
    saveBOM(data) { return this.call('/bom/save', 'POST', data); },
    saveBOMOrder(data) { return this.call('/bom/save-order', 'POST', data); },

    getApprovalOrders() { return this.call('/approval/orders'); },
    approveCosting(data) { return this.call('/approval/approve', 'POST', data); },
    rejectCosting(data) { return this.call('/approval/reject', 'POST', data); },

    getRMOrders() { return this.call('/rm-order/orders'); },
    generatePO(data) { return this.call('/rm-order/generate-po', 'POST', data); },
    processPO(poToken) { return this.call('/rm-order/process', 'POST', { po_token: poToken }); },
    savePO(poToken) { return this.call('/rm-order/save', 'POST', { po_token: poToken }); },

    getRMInspections() { return this.call('/rm-inspection/orders'); },
    saveRMInspection(data) { return this.call('/rm-inspection/save', 'POST', data); },

    getGRNOrders() { return this.call('/grn/orders'); },
    getGRNBuyerOrders() { return this.call('/grn/buyer-orders'); },
    getGRNOrdersByBuyer(buyerOrderId) { return this.call('/grn/orders?buyer_order_id=' + encodeURIComponent(buyerOrderId)); },
    getPendingShortfalls() { return this.call('/grn/shortfalls'); },
    saveGRN(data) { return this.call('/grn/save', 'POST', data); },
    cancelGRN(poToken, invoiceNo) { return this.call('/grn/cancel', 'POST', { po_token: poToken, invoice_no: invoiceNo }); },

    getInternalFGOrders() { return this.call('/internal-fg/orders'); },
    saveInternalFGOrder(data) { return this.call('/internal-fg/save', 'POST', data); },

    getIssueRMOrders() { return this.call('/issue-rm/orders'); },
    getIssuableItems(fgKey) { return this.call(`/issue-rm/${encodeURIComponent(fgKey)}/items`); },
    saveIssueRM(data) { return this.call('/issue-rm/save', 'POST', data); },

    getFGInspections() { return this.call('/fg-inspection/orders'); },
    saveFGInspection(data) { return this.call('/fg-inspection/save', 'POST', data); },

    getFGInventory() { return this.call('/fg-inventory/items'); },

    getReportData(reportType, filters) { return this.call('/reports/data', 'POST', { reportType, filters }); },
    getReportFilters() { return this.call('/reports/filters'); },

    debugFGStatus(fgKey) { return this.call(`/utils/debug/fg-status?fg_key=${encodeURIComponent(fgKey)}`); },
    cancelStage(data) { return this.call('/utils/cancel/stage', 'POST', data); },
    cancelOrder(data) { return this.call('/utils/cancel/order', 'POST', data); },
    getWorkflow() { return this.call('/utils/workflow'); },
    getSettings() { return this.call('/utils/settings'); },
};

// ==============================================================
// SECTION 4: TOAST & NOTIFICATIONS
// ==============================================================

function showToast(msg, type = '') {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast show ' + type;
    clearTimeout(t._timeout);
    t._timeout = setTimeout(() => { t.className = 'toast'; }, 4000);
}

// ==============================================================
// SECTION 5: MODAL CONTROLS
// ==============================================================

function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.add('active');
        const bomModal = document.getElementById('bomAssignmentModal');
        if (bomModal) {
            modal.style.zIndex = '10001';
        } else {
            modal.style.zIndex = '1000';
        }
        const box = modal.querySelector('.modal-box');
        if (box) box.style.zIndex = '10002';
    }
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.remove('active');
        modal.style.zIndex = '';
        const box = modal.querySelector('.modal-box');
        if (box) box.style.zIndex = '';
    }
}

// ==============================================================
// SECTION 6: THEME CONTROLS
// ==============================================================

function toggleTheme() {
    const html = document.documentElement;
    const icon = document.getElementById('themeIcon');
    const current = html.getAttribute('data-theme');
    if (current === 'dark') {
        html.removeAttribute('data-theme');
        if (icon) icon.className = 'fas fa-moon';
        localStorage.setItem('theme', 'light');
    } else {
        html.setAttribute('data-theme', 'dark');
        if (icon) icon.className = 'fas fa-sun';
        localStorage.setItem('theme', 'dark');
    }
}

function loadTheme() {
    const saved = localStorage.getItem('theme');
    const html = document.documentElement;
    const icon = document.getElementById('themeIcon');
    if (saved === 'dark') {
        html.setAttribute('data-theme', 'dark');
        if (icon) icon.className = 'fas fa-sun';
    } else {
        html.removeAttribute('data-theme');
        if (icon) icon.className = 'fas fa-moon';
    }
}

// ==============================================================
// SECTION 7: AUTHENTICATION
// ==============================================================

function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    window.location.href = '/login';
}

function getUserRole() {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    currentUserRole = user.role || 'viewer';
    return currentUserRole;
}

// ==============================================================
// SECTION 8: TABLE FILTER & UTILITY
// ==============================================================

function filterTable(searchInputId, containerId, rowSelector = "tr") {
    const input = document.getElementById(searchInputId);
    if (!input) return;
    const filter = input.value.toLowerCase();
    const container = document.getElementById(containerId);
    if (!container) return;

    if (container.tagName === "TBODY") {
        const rows = container.querySelectorAll("tr");
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(filter) ? "" : "none";
        });
        return;
    }

    const rows = container.querySelectorAll(rowSelector);
    if (rows.length === 0 && container.children.length > 0) {
        const cards = container.querySelectorAll(".po-card");
        cards.forEach(card => {
            const text = card.textContent.toLowerCase();
            card.style.display = text.includes(filter) ? "" : "none";
        });
        return;
    }

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(filter) ? "" : "none";
    });
}

function safeDate(date) {
    if (!date) return '—';
    try {
        const d = new Date(date);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN');
    } catch (e) { return '—'; }
}

function getStatusBadge(status) {
    const map = {
        'DRAFT': 'draft', 'PENDING': 'pending', 'COMPLETED': 'completed',
        'APPROVED': 'approved', 'PROCESSED': 'processed', 'PARTIAL': 'partial',
        'CANCELLED': 'cancelled', 'REJECTED': 'rejected', 'PASSED': 'passed',
        'ACTIVE': 'active', 'INACTIVE': 'inactive', 'CLOSED': 'closed',
        'READY': 'ready', 'DISPATCHED': 'dispatched'
    };
    return map[status] || 'pending';
}

// ==============================================================
// SECTION 9: BOM AUTOCOMPLETE & CALCULATIONS
// ==============================================================

function setupBOMAutocomplete() {
    let itemDatalist = document.getElementById('itemDatalist');
    if (!itemDatalist) {
        itemDatalist = document.createElement('datalist');
        itemDatalist.id = 'itemDatalist';
        document.body.appendChild(itemDatalist);
        fetch('/master/inventory/', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        })
        .then(response => response.json())
        .then(items => {
            itemDatalist.innerHTML = '';
            items.forEach(item => {
                const opt = document.createElement('option');
                const id = item.id || item.item_no || '';
                const name = item.name || item.item_name || '';
                opt.value = id;
                opt.textContent = id + ' - ' + name;
                itemDatalist.appendChild(opt);
            });
        })
        .catch(e => console.error('Error loading items:', e));
    }

    let supplierDatalist = document.getElementById('supplierDatalist');
    if (!supplierDatalist) {
        supplierDatalist = document.createElement('datalist');
        supplierDatalist.id = 'supplierDatalist';
        document.body.appendChild(supplierDatalist);
        fetch('/master/suppliers', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        })
        .then(response => response.json())
        .then(suppliers => {
            supplierDatalist.innerHTML = '';
            suppliers.forEach(s => {
                const opt = document.createElement('option');
                const name = s.name || s;
                opt.value = name;
                opt.textContent = name;
                supplierDatalist.appendChild(opt);
            });
        })
        .catch(e => console.error('Error loading suppliers:', e));
    }

    document.querySelectorAll('.bom-item-no').forEach(input => {
        input.setAttribute('list', 'itemDatalist');
        input.addEventListener("change", function() { autoFillBOMItem(this); });
        input.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); autoFillBOMItem(this); } });
    });

    document.querySelectorAll('.bom-supplier').forEach(input => {
        input.setAttribute('list', 'supplierDatalist');
    });

    document.querySelectorAll('.bom-consumption, .bom-rate').forEach(input => {
        input.addEventListener('input', function() { calculateBOMTotal(); });
    });
}

function autoFillBOMItem(input) {
    const itemNo = input.value.trim();
    if (!itemNo) return;
    const row = input.closest('tr');
    if (!row) return;

    fetch('/master/inventory/', {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
    })
    .then(response => response.json())
    .then(items => {
        const found = items.find(i => i.id === itemNo || i.item_no === itemNo);
        if (found) {
            row.querySelector('.bom-item-name').value = found.name || found.item_name || '';
            row.querySelector('.bom-color').value = found.color || '';
            row.querySelector('.bom-uom').value = found.uom || 'PCS';
            row.querySelector(".bom-size").value = (found.extra_data && found.extra_data.size) || found.size || "";
            row.querySelector('.bom-rate').value = found.rate || found.standard_rate || 0;
            row.querySelector('.bom-supplier').value = found.supplier || found.preferred_supplier || '';
            showToast('Auto-filled: ' + (found.name || found.item_name), 'success');
            setTimeout(calculateBOMTotal, 200);
        } else {
            showToast('Item not found', 'warning');
        }
    })
    .catch(e => console.error('Auto-fill error:', e));
}

function calculateBOMTotal() {
    const fgContainers = document.querySelectorAll('[id^="bomRows-"]');
    fgContainers.forEach(tbody => {
        const fgIdx = tbody.id.replace('bomRows-', '');
        const rows = tbody.querySelectorAll('tr');
        let totalCost = 0;
        let totalConsumption = 0;
        rows.forEach(row => {
            const consumption = parseFloat(row.querySelector('.bom-consumption').value) || 0;
            const rate = parseFloat(row.querySelector('.bom-rate').value) || 0;
            totalCost += consumption * rate;
            totalConsumption += consumption;
        });
        let totalRow = document.getElementById('bomTotal-' + fgIdx);
        if (!totalRow) {
            const parent = tbody.parentElement;
            const div = document.createElement('div');
            div.id = 'bomTotal-' + fgIdx;
            div.style.cssText = 'padding:8px 12px;margin-top:8px;background:var(--table-header);border-radius:4px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;';
            div.innerHTML = `<span style="font-weight:600;color:var(--text-primary);">Total Cost per PC: <span id="bomTotalValue-${fgIdx}" style="color:var(--nav-active-text);">Rs.${totalCost.toFixed(2)}</span></span>
                <span style="color:var(--text-muted);font-size:12px;">Total Consumption: ${totalConsumption.toFixed(2)} units</span>`;
            parent.appendChild(div);
        } else {
            document.getElementById('bomTotalValue-' + fgIdx).textContent = 'Rs.' + totalCost.toFixed(2);
        }
    });
}

function removeBOMRow(btn) {
    const tr = btn.closest('tr');
    if (!tr) return;
    const tbody = tr.parentElement;
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    if (rows.length <= 1) {
        showToast('Cannot remove last row', 'warning');
        return;
    }
    tr.remove();
    setTimeout(calculateBOMTotal, 200);
}

window.removeBOMRow = removeBOMRow;

// ==============================================================
// SECTION 10: STAGE 0 - BUYER ORDER
// ==============================================================

async function loadBuyers() {
    try {
        const buyers = await API.getBuyers();
        const sel = document.getElementById('buyerName');
        const cur = sel.value;
        sel.innerHTML = '<option value="">Select Buyer</option>';
        if (buyers && buyers.length) {
            buyers.forEach(b => {
                const name = b.name || b;
                sel.innerHTML += `<option value="${name}">${name}</option>`;
            });
        }
        if (cur) sel.value = cur;
        ERP_STATE.buyerName = sel.value;
    } catch (e) {
        showToast('Error loading buyers: ' + e.message, 'error');
    }
}

async function loadBuyerDetails() {
    const name = document.getElementById('buyerName').value;
    ERP_STATE.buyerName = name;
    if (!name) {
        document.getElementById('buyerGST').value = '';
        ERP_STATE.buyerGST = '';
        return;
    }
    try {
        const response = await fetch('/master/buyers', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        const buyers = await response.json();
        const buyer = buyers.find(b => b.name === name);
        if (buyer && buyer.gst_no) {
            document.getElementById('buyerGST').value = buyer.gst_no;
            ERP_STATE.buyerGST = buyer.gst_no;
        } else {
            document.getElementById('buyerGST').value = '';
        }
    } catch (e) {
        showToast('Error loading buyer details: ' + e.message, 'error');
    }
}

function openBuyerModal() {
    document.getElementById('buyerModal').classList.add('active');
    ['newBuyerName', 'newGstNo', 'newAddress', 'newContactPerson', 'newContactNo', 'newPaymentTerm'].forEach(id => {
        document.getElementById(id).value = '';
    });
}

function closeBuyerModal() {
    document.getElementById('buyerModal').classList.remove('active');
}

async function addNewBuyer() {
    const data = {
        name: document.getElementById('newBuyerName').value.trim(),
        gst_no: document.getElementById('newGstNo').value.trim(),
        address: document.getElementById('newAddress').value.trim(),
        contact_person: document.getElementById('newContactPerson').value.trim(),
        contact_no: document.getElementById('newContactNo').value.trim(),
        payment_term: document.getElementById('newPaymentTerm').value.trim()
    };
    if (!data.name || !data.gst_no) {
        showToast('Buyer name and GST are required', 'error');
        return;
    }
    try {
        const r = await API.addBuyer(data);
        if (r.success) {
            showToast(r.message, 'success');
            closeBuyerModal();
            loadBuyers();
            document.getElementById('buyerName').value = data.name;
            loadBuyerDetails();
        } else {
            showToast(r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function setDefaultDates() {
    const today = new Date();
    document.getElementById('orderDate').value = today.toISOString().split('T')[0];
    ERP_STATE.orderDate = document.getElementById('orderDate').value;
    const d = new Date(today);
    d.setDate(today.getDate() + 15);
    document.getElementById('deliveryDate').value = d.toISOString().split('T')[0];
    ERP_STATE.deliveryDate = document.getElementById('deliveryDate').value;
    calculateLeadTime();
}

function calculateLeadTime() {
    const order = document.getElementById('orderDate').value;
    const delivery = document.getElementById('deliveryDate').value;
    ERP_STATE.orderDate = order;
    ERP_STATE.deliveryDate = delivery;
    if (order && delivery) {
        const diff = Math.ceil((new Date(delivery) - new Date(order)) / (1000 * 60 * 60 * 24));
        document.getElementById('leadTime').value = diff > 0 ? diff : 0;
        ERP_STATE.leadTime = diff > 0 ? diff : 0;
    }
}

async function generateAutoSerial() {
    try {
        const s = await API.generateFGSerial();
        const serial = s.serial || s || 'FG-000000-001';
        document.getElementById('fgOrderSerial').value = serial;
        ERP_STATE.currentFGOrderSerial = serial;
    } catch (e) {
        document.getElementById('fgOrderSerial').value = 'FG-000000-001';
        ERP_STATE.currentFGOrderSerial = 'FG-000000-001';
    }
}

async function generateGrid() {
    ERP_STATE.buyerName = document.getElementById('buyerName').value;
    ERP_STATE.buyerGST = document.getElementById('buyerGST').value;
    ERP_STATE.buyerOrderNo = document.getElementById('buyerOrderNo').value.trim();
    ERP_STATE.orderDate = document.getElementById('orderDate').value;
    ERP_STATE.deliveryDate = document.getElementById('deliveryDate').value;
    ERP_STATE.leadTime = parseInt(document.getElementById('leadTime').value) || 0;
    ERP_STATE.noOfFG = parseInt(document.getElementById('noOfFG').value) || 0;

    if (!ERP_STATE.buyerName || !ERP_STATE.buyerOrderNo || !ERP_STATE.orderDate || !ERP_STATE.deliveryDate) {
        showToast('Please fill all required fields', 'error');
        return;
    }
    if (ERP_STATE.noOfFG < 1) {
        showToast('Please enter number of FG', 'error');
        return;
    }

    const orderData = {
        buyer_name: ERP_STATE.buyerName,
        buyer_gst: ERP_STATE.buyerGST,
        buyer_order_no: ERP_STATE.buyerOrderNo,
        order_date: ERP_STATE.orderDate,
        delivery_date: ERP_STATE.deliveryDate,
        lead_time: ERP_STATE.leadTime,
        no_of_fg: ERP_STATE.noOfFG
    };

    showToast('Generating grid...', 'info');
    try {
        const r = await API.generateOrderGrid(orderData);
        if (r.success) {
            ERP_STATE.currentFGOrderSerial = r.fg_order_serial;
            document.getElementById('fgOrderSerial').value = r.fg_order_serial;
            const cleanGrid = r.grid_data.map(row => {
                const sizes = r.sizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
                const sizeCount = sizes.length;
                const cleanRow = [row[0], row[1], row[2]];
                for (let i = 3; i < 3 + sizeCount; i++) {
                    cleanRow.push(row[i] || 0);
                }
                return cleanRow;
            });
            ERP_STATE.gridData = cleanGrid;
            renderGrid(cleanGrid, r.fg_order_serial);
            document.getElementById('gridSection').style.display = 'block';
            showToast('Grid ready!', 'success');
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function renderGrid(gridData, fgOrderSerial) {
    if (!gridData || !gridData.length) {
        showToast('No data', 'error');
        return;
    }
    const defaultSizes = [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
    const sizeCount = gridData[0].length - 3;
    const sizeHeaders = defaultSizes.slice(0, sizeCount);
    document.getElementById('gridOrderSerial').textContent = `Order: ${fgOrderSerial}`;

    let h = '<tr><th>#</th><th>FG Design No</th><th>FG Color No</th>';
    sizeHeaders.forEach(s => h += `<th style="min-width:60px;">${s}</th>`);
    h += '</tr>';
    document.getElementById('gridHeaders').innerHTML = h;

    let b = '';
    gridData.forEach((row, idx) => {
        b += `<tr><td><strong>${idx + 1}</strong></td>`;
        b += `<td><input type="text" value="${row[1] || ''}" data-row="${idx}" data-col="1" placeholder="Design" style="min-width:100px;width:100px;"></td>`;
        b += `<td><input type="text" value="${row[2] || ''}" data-row="${idx}" data-col="2" placeholder="Color" style="min-width:100px;width:100px;"></td>`;
        for (let i = 3; i < 3 + sizeCount; i++) {
            const val = (row[i] === 0 || row[i] === '' || row[i] === null) ? '' : row[i];
            b += `<td><input type="number" value="${val}" data-row="${idx}" data-col="${i}" placeholder="0" style="width:80px;min-width:80px;"></td>`;
        }
        b += '</tr>';
    });
    document.getElementById('gridBody').innerHTML = b;
}

async function saveOrder() {
    const sizeHeaders = document.querySelectorAll('#gridHeaders th');
    const sizes = [];
    sizeHeaders.forEach((th, idx) => {
        if (idx > 2) {
            const val = parseInt(th.textContent);
            if (!isNaN(val)) sizes.push(val);
        }
    });

    const rows = document.querySelectorAll('#gridBody tr');
    const allData = [];
    const buyerName = ERP_STATE.buyerName || document.getElementById('buyerName').value || 'Unknown';
    const buyerOrderNo = ERP_STATE.buyerOrderNo || document.getElementById('buyerOrderNo').value || 'N/A';
    const orderDate = ERP_STATE.orderDate || document.getElementById('orderDate').value || new Date().toISOString().split('T')[0];
    const createdDate = new Date().toISOString();

    try {
        const existingOrders = await API.getBuyerOrders(false);
        const duplicate = existingOrders.find(o => o.buyerName === buyerName && o.buyerOrderNo === buyerOrderNo && o.status !== 'CANCELLED');
        if (duplicate) {
            showToast('[ERR] Order already exists for Buyer: ' + buyerName + ' with Order No: ' + buyerOrderNo, 'error');
            return;
        }
    } catch (e) {
        console.error('Deduplication check failed:', e);
    }

    rows.forEach((row, idx) => {
        const inputs = row.querySelectorAll('input');
        const rowData = [ERP_STATE.currentFGOrderSerial];
        rowData.push(inputs[0] ? inputs[0].value.trim() : '');
        rowData.push(inputs[1] ? inputs[1].value.trim() : '');
        for (let i = 2; i < inputs.length; i++) {
            const val = inputs[i].value;
            rowData.push(val === '' ? 0 : parseFloat(val) || 0);
        }
        rowData.push(buyerName);
        rowData.push(buyerOrderNo);
        rowData.push(orderDate);
        rowData.push(createdDate);
        allData.push(rowData);
    });

    for (let i = 0; i < allData.length; i++) {
        if (!allData[i][1] || !allData[i][2]) {
            showToast(`Row ${i + 1}: Design and Color are required`, 'error');
            return;
        }
    }
    if (!buyerName || buyerName === 'Unknown') {
        showToast('Please select a Buyer', 'error');
        return;
    }
    if (!buyerOrderNo || buyerOrderNo === 'N/A') {
        showToast('Please enter Buyer Order No', 'error');
        return;
    }

    const btn = document.getElementById('saveBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    try {
        const r = await API.saveOrder({
            fg_order_serial: ERP_STATE.currentFGOrderSerial,
            grid_data: allData,
            sizes: sizes
        });
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-save"></i> Save Order';
        if (r.success) {
            showToast('Order saved!', 'success');
            document.getElementById('gridSection').style.display = 'none';
            document.getElementById('buyerOrderNo').value = '';
            document.getElementById('noOfFG').value = '';
            ERP_STATE.buyerOrderNo = '';
            ERP_STATE.noOfFG = 0;
            generateAutoSerial();
            setDefaultDates();
            closeModal('createOrderModal');
            refreshBuyerOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-save"></i> Save Order';
        showToast('Error: ' + e.message, 'error');
    }
}

function renderBuyerOrders(orders) {
    const tb = document.getElementById('buyerOrderBody');
    if (!tb) return;
    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#62748e;padding:16px;">No orders found</td></tr>';
        return;
    }
    let html = '';
    orders.forEach(o => {
        const statusDisplay = (o.status === 'CANCELLED') ? 'CANCELLED' : 'ACTIVE';
        const statusClass = statusDisplay === 'CANCELLED' ? 'danger' : 'success';
        const isCancelled = statusDisplay === 'CANCELLED';
        const orderId = o.buyerOrderId || '—';
        html += '<tr>';
        html += `<td><strong>${orderId}</strong></td>`;
        html += `<td>${o.buyerName || '—'}</td>`;
        html += `<td>${o.buyerOrderNo || '—'}</td>`;
        html += `<td>${safeDate(o.orderDate)}</td>`;
        html += `<td>${o.totalFGs || 0}</td>`;
        html += `<td>${safeDate(o.lastUpdated || o.orderDate)}</td>`;
        html += `<td><span class="status-badge ${statusClass}">${statusDisplay}</span></td>`;
        html += '<td>';
        if (!isCancelled) {
            html += `<button class="btn btn-primary btn-sm" onclick="openOrderActions('${orderId}')">Actions</button>`;
        } else {
            html += '<span class="text-muted" style="font-size:10px;">—</span>';
        }
        html += '</td></tr>';
    });
    tb.innerHTML = html;
    const countEl = document.getElementById('orderCount');
    if (countEl) countEl.textContent = orders.length + ' orders';
}

function refreshBuyerOrders() {
    showToast('Loading orders...', 'info');
    const showCancelled = document.getElementById('showCancelledBO_BO') && document.getElementById('showCancelledBO_BO').checked;

    API.getBuyerOrders(showCancelled)
    .then(data => {
        const countEl = document.getElementById('buyerCount');
        if (countEl) countEl.textContent = data.length;
        const orderCountEl = document.getElementById('orderCount');
        if (orderCountEl) orderCountEl.textContent = data.length + ' orders';
        renderBuyerOrders(data);
        showToast(data.length + ' orders loaded', 'success');
    })
    .catch(e => {
        showToast('Error loading orders: ' + e.message, 'error');
    });
}

function openOrderActions(orderId) {
    const modal = document.createElement('div');
    modal.id = 'orderActionsModal';
    modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:flex;justify-content:center;align-items:center;z-index:9999;';
    modal.innerHTML = `
        <div style="background:var(--bg-card);border-radius:12px;padding:24px;max-width:420px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3);border:1px solid var(--border-color);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <h3 style="margin:0;color:var(--text-primary);">Order Actions</h3>
                <button onclick="this.closest('#orderActionsModal').remove()" style="background:none;border:none;font-size:24px;cursor:pointer;color:var(--text-muted);">x</button>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <button class="btn btn-success" style="padding:12px;font-size:14px;width:100%;" onclick="processOrderToStage('${orderId}', 'BOM_COSTING');document.getElementById('orderActionsModal').remove();">Process to BOM</button>
                <button class="btn btn-info" style="padding:12px;font-size:14px;width:100%;" onclick="printOrder('${orderId}');document.getElementById('orderActionsModal').remove();">Print</button>
                <button class="btn btn-primary" style="padding:12px;font-size:14px;width:100%;" onclick="editBuyerOrder('${orderId}');document.getElementById('orderActionsModal').remove();">Edit</button>
                <button class="btn btn-danger" style="padding:12px;font-size:14px;width:100%;" onclick="cancelBuyerOrder('${orderId}');document.getElementById('orderActionsModal').remove();">Cancel</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', function(e) {
        if (e.target === modal) modal.remove();
    });
}

function cancelBuyerOrder(orderId) {
    const password = prompt('[WARN] Enter your password to confirm cancellation:');
    if (!password) return;
    fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'admin@sneha.com', password: password })
    })
    .then(response => {
        if (!response.ok) throw new Error('Invalid password');
        return response.json();
    })
    .then(() => {
        if (!confirm('[WARN] Are you sure you want to CANCEL order ' + orderId + '?\nThis will change status to CANCELLED and cannot be undone.')) return;
        showToast('Cancelling order ' + orderId + '...', 'info');
        API.cancelBuyerOrder(orderId)
        .then(result => {
            if (result.success) {
                showToast('Order ' + orderId + ' cancelled', 'success');
                refreshBuyerOrders();
            } else {
                showToast(result.message || 'Error cancelling order', 'error');
            }
        })
        .catch(e => showToast('Error: ' + e.message, 'error'));
    })
    .catch(e => showToast('Invalid password: ' + e.message, 'error'));
}

function printOrder(orderId) {
    showToast('Generating print for ' + orderId + '...', 'info');
    window.open('/buyer-order/print/' + orderId, '_blank');
}

function editBuyerOrder(orderId) {
    showToast('Loading order ' + orderId + '...', 'info');

    fetch('/master/buyers', {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
    })
    .then(res => res.json())
    .then(buyers => {
        const sel = document.getElementById('editBuyerName');
        sel.innerHTML = '<option value="">Select Buyer</option>';
        buyers.forEach(b => {
            const opt = document.createElement('option');
            opt.value = b.name;
            opt.textContent = b.name;
            sel.appendChild(opt);
        });
    })
    .catch(() => {});

    API.getBuyerOrders(false)
    .then(orders => {
        const order = orders.find(o => o.buyerOrderId === orderId);
        if (!order) {
            showToast('Order not found', 'error');
            return;
        }
        document.getElementById('editFgOrderSerial').value = orderId;
        document.getElementById('editBuyerName').value = order.buyerName || '';
        document.getElementById('editBuyerOrderNo').value = order.buyerOrderNo || '';
        document.getElementById('editOrderDate').value = order.orderDate ? order.orderDate.split('T')[0] : '';
        document.getElementById('editNoOfFG').value = order.totalFGs || 1;
        loadEditBuyerDetails();

        API.getOrderGrid(orderId)
        .then(data => {
            if (data.success && data.grid_data && data.grid_data.length > 0) {
                const sizes = data.sizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
                window._editSizes = sizes;
                renderEditGrid(data.grid_data, sizes);
                showToast('Order loaded for editing', 'success');
            } else {
                showToast('No grid data found for this order', 'error');
                generateEditGrid();
            }
        })
        .catch(() => generateEditGrid());
        openModal('editBuyerOrderModal');
    })
    .catch(e => showToast('Error loading order: ' + e.message, 'error'));
}

function loadEditBuyerDetails() {
    const name = document.getElementById('editBuyerName').value;
    if (!name) {
        document.getElementById('editBuyerGST').value = '';
        return;
    }
    fetch('/master/buyers', {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
    })
    .then(res => res.json())
    .then(buyers => {
        const buyer = buyers.find(b => b.name === name);
        if (buyer) document.getElementById('editBuyerGST').value = buyer.gst_no || '';
    })
    .catch(() => {});
}

function generateEditGrid() {
    const fgs = parseInt(document.getElementById('editNoOfFG').value) || 1;
    const sizes = window._editSizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
    const tb = document.getElementById('editGridBody');
    if (!tb) return;
    tb.innerHTML = '';
    for (let i = 0; i < fgs; i++) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i + 1}</td>`;
        tr.innerHTML += '<td><input type="text" class="edit-fg-des" placeholder="Design" style="min-width:70px;"></td>';
        tr.innerHTML += '<td><input type="text" class="edit-fg-col" placeholder="Color" style="min-width:70px;"></td>';
        for (let j = 0; j < sizes.length; j++) {
            tr.innerHTML += '<td><input type="number" class="edit-fg-qty" value="0" min="0" style="width:70px;"></td>';
        }
        const td = document.createElement('td');
        td.innerHTML = '<button class="btn btn-danger btn-xs" onclick="removeEditFGRow(this)"><i class="fas fa-times"></i></button>';
        tr.appendChild(td);
        tb.appendChild(tr);
    }
    updateEditGridHeaders(sizes);
}

function renderEditGrid(gridData, sizes) {
    window._editSizes = sizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
    const tb = document.getElementById('editGridBody');
    if (!tb) return;
    tb.innerHTML = '';
    for (let idx = 0; idx < gridData.length; idx++) {
        const row = gridData[idx];
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${idx + 1}</td>`;
        tr.innerHTML += `<td><input type="text" class="edit-fg-des" value="${row[1] || ''}" placeholder="Design" style="min-width:70px;"></td>`;
        tr.innerHTML += `<td><input type="text" class="edit-fg-col" value="${row[2] || ''}" placeholder="Color" style="min-width:70px;"></td>`;
        for (let i = 0; i < window._editSizes.length; i++) {
            const colIndex = 3 + i;
            const val = (colIndex < row.length - 4) ? (row[colIndex] || 0) : 0;
            tr.innerHTML += `<td><input type="number" class="edit-fg-qty" value="${val}" min="0" style="width:70px;"></td>`;
        }
        const td = document.createElement('td');
        td.innerHTML = '<button class="btn btn-danger btn-xs" onclick="removeEditFGRow(this)"><i class="fas fa-times"></i></button>';
        tr.appendChild(td);
        tb.appendChild(tr);
    }
    document.getElementById('editNoOfFG').value = gridData.length;
    updateEditGridHeaders(window._editSizes);
}

function updateEditGridHeaders(sizes) {
    let headers = '<tr><th>#</th><th>Design*</th><th>Color*</th>';
    for (let i = 0; i < sizes.length; i++) {
        headers += `<th>${sizes[i]}</th>`;
    }
    headers += '<th>Action</th></tr>';
    document.getElementById('editGridHeaders').innerHTML = headers;
}

function addEditFGRow() {
    const sizes = window._editSizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
    const tb = document.getElementById('editGridBody');
    if (!tb) return;
    const rowIdx = tb.children.length;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${rowIdx + 1}</td>`;
    tr.innerHTML += '<td><input type="text" class="edit-fg-des" placeholder="Design" style="min-width:70px;"></td>';
    tr.innerHTML += '<td><input type="text" class="edit-fg-col" placeholder="Color" style="min-width:70px;"></td>';
    for (let i = 0; i < sizes.length; i++) {
        tr.innerHTML += '<td><input type="number" class="edit-fg-qty" value="0" min="0" style="width:70px;"></td>';
    }
    const td = document.createElement('td');
    td.innerHTML = '<button class="btn btn-danger btn-xs" onclick="removeEditFGRow(this)"><i class="fas fa-times"></i></button>';
    tr.appendChild(td);
    tb.appendChild(tr);
    updateEditFGRowNumbers();
}

function removeEditFGRow(btn) {
    const tr = btn.closest('tr');
    if (tr) {
        const tb = tr.parentElement;
        if (tb && tb.children.length <= 1) {
            showToast('Cannot remove last FG row', 'error');
            return;
        }
        tr.remove();
        updateEditFGRowNumbers();
    }
}

function updateEditFGRowNumbers() {
    const rows = document.querySelectorAll('#editGridBody tr');
    rows.forEach((row, i) => {
        const td = row.querySelector('td:first-child');
        if (td) td.textContent = i + 1;
    });
}

function saveEditOrder() {
    const orderId = document.getElementById('editFgOrderSerial').value;
    const buyerName = document.getElementById('editBuyerName').value;
    const buyerOrderNo = document.getElementById('editBuyerOrderNo').value.trim();
    const orderDate = document.getElementById('editOrderDate').value;

    if (!buyerName || !buyerOrderNo || !orderDate) {
        showToast('Please fill all required fields', 'error');
        return;
    }

    const rows = document.querySelectorAll('#editGridBody tr');
    const gridData = [];
    for (let idx = 0; idx < rows.length; idx++) {
        const row = rows[idx];
        const des = row.querySelector('.edit-fg-des').value.trim();
        const col = row.querySelector('.edit-fg-col').value.trim();
        if (!des || !col) {
            showToast('Please fill Design and Color for all FGs', 'error');
            return;
        }
        const rowData = [orderId, des, col];
        const qtyInputs = row.querySelectorAll('.edit-fg-qty');
        for (let j = 0; j < qtyInputs.length; j++) {
            rowData.push(parseFloat(qtyInputs[j].value) || 0);
        }
        rowData.push(buyerName);
        rowData.push(buyerOrderNo);
        rowData.push(orderDate);
        rowData.push(new Date().toISOString());
        gridData.push(rowData);
    }

    const btn = document.getElementById('editSaveBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';

    fetch('/buyer-order/update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + localStorage.getItem('access_token')
        },
        body: JSON.stringify({
            buyer_order_id: orderId,
            grid_data: gridData,
            buyer_name: buyerName,
            buyer_order_no: buyerOrderNo,
            order_date: orderDate,
            sizes: window._editSizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54]
        })
    })
    .then(response => response.json())
    .then(result => {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-save"></i> Update Order';
        if (result.success) {
            showToast('Order updated successfully', 'success');
            closeModal('editBuyerOrderModal');
            refreshBuyerOrders();
        } else {
            showToast(result.message || 'Error updating order', 'error');
        }
    })
    .catch(e => {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-save"></i> Update Order';
        showToast('Error: ' + e.message, 'error');
    });
}

function processOrderToStage(orderId, targetStage) {
    showToast('Processing order ' + orderId + ' to ' + targetStage + '...', 'info');
    if (targetStage === 'BOM_COSTING') {
        const bomTab = document.querySelector('[data-module="BOM_COSTING"]');
        if (bomTab) bomTab.click();
        setTimeout(() => {
            openBOMModalForOrder(orderId);
        }, 500);
    } else {
        showToast('Stage ' + targetStage + ' processing not yet implemented', 'warning');
    }
}

async function cancelStageAction(fgKey, stage) {
    if (!confirm(`[WARN] Are you sure you want to CANCEL ${stage} for Order: ${fgKey}?`)) return;
    showToast(`Cancelling ${stage}...`, 'info');
    try {
        const r = await API.cancelStage({ fgKey, targetStage: stage });
        if (r.success) {
            showToast(r.message, 'success');
            refreshBOMOrders();
            refreshBuyerOrders();
            refreshRMOrders();
            refreshGRNOrders();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 11: STAGE 1 - BOM COSTING
// ==============================================================

async function refreshBOMOrders() {
    console.log("[DEBUG] refreshBOMOrders called");
    showToast('Loading BOM orders...', 'info');
    try {
        const bomData = await API.getBOMOrders();
        if (!bomData || bomData.length === 0) {
            document.getElementById('bomCount').textContent = '0';
            renderBOMOrders([]);
            showToast('No BOM orders found', 'info');
            return;
        }
        const orders = bomData.map(item => ({
            fgOrderSerial: item.buyerOrderId,
            buyerName: item.buyerName || 'Unknown',
            buyerOrderNo: item.buyerOrderNo || 'N/A',
            orderDate: item.orderDate,
            totalFGs: item.totalFGs || 0,
            bomStatus: item.bomStatus || 'COMPLETED',
            status: item.status || 'BOM_READY'
        }));
        document.getElementById('bomCount').textContent = orders.length;
        renderBOMOrders(orders);
        showToast(orders && orders.length ? 'BOM orders loaded' : 'No BOM orders found', orders && orders.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading BOM orders: ' + e.message, 'error');
    }
}

function renderBOMOrders(orders) {
    const tb = document.getElementById('bomOrderBody');
    if (!tb) return;
    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#62748e;padding:16px;">No BOM orders found</td></tr>';
        return;
    }
    let html = '';
    orders.forEach(o => {
        const orderId = o.fgOrderSerial || o.buyerOrderId;
        html += `<tr>
            <td><strong>${orderId}</strong></td>
            <td>${o.buyerName || '—'}</td>
            <td>${o.buyerOrderNo || '—'}</td>
            <td>${safeDate(o.orderDate)}</td>
            <td><span class="badge-status info">${o.totalFGs || 0}</span></td>
            <td>
                <button class="btn btn-primary btn-sm" onclick="editBOMModal('${orderId}')">
                    <i class="fas fa-edit"></i> Edit BOM
                </button>
                <button class="btn btn-danger btn-sm" onclick="cancelBOM('${orderId}')">
                    <i class="fas fa-undo"></i> Cancel BOM
                </button>
                <button class="btn btn-success btn-sm" onclick="submitBOMForApproval('${orderId}')">
                    <i class="fas fa-check"></i> Submit for Approval
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

// ==============================================================
// BOM ASSIGNMENT MODAL FUNCTIONS
// ==============================================================

async function openBOMModalForOrder(orderId) {
    showToast('Loading FGs for ' + orderId + '...', 'info');
    try {
        const result = await API.getOrderGrid(orderId);
        if (!result.success) {
            showToast('Error loading order: ' + result.message, 'error');
            return;
        }
        ERP_STATE.bomOrderId = orderId;
        ERP_STATE.bomGridData = result.grid_data || [];
        ERP_STATE.bomSizes = result.sizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
        ERP_STATE.isBOMAssignmentOpen = true;
        renderBOMModal();
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function editBOMModal(orderId) {
    showToast('Loading BOM for ' + orderId + '...', 'info');
    fetch('/bom/order/' + orderId, {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success && data.fgs) {
            ERP_STATE.bomOrderId = orderId;
            return fetch('/buyer-order/grid/' + orderId, {
                headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
            })
            .then(res => res.json())
            .then(gridResult => {
                if (gridResult.success) {
                    ERP_STATE.bomGridData = gridResult.grid_data || [];
                    ERP_STATE.bomSizes = gridResult.sizes || [26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54];
                    renderBOMModalWithExistingData(data.fgs);
                } else {
                    showToast('Error loading grid data', 'error');
                }
            });
        } else {
            showToast('No existing BOM found for this order, opening empty BOM', 'warning');
            openBOMModalForOrder(orderId);
        }
    })
    .catch(() => {
        showToast('Error loading BOM data, opening empty BOM', 'error');
        openBOMModalForOrder(orderId);
    });
}

function renderBOMModal() {
    const orderId = ERP_STATE.bomOrderId;
    const gridData = ERP_STATE.bomGridData || [];
    const sizes = ERP_STATE.bomSizes || [];

    if (!gridData.length) {
        showToast('No FGs found for this order', 'error');
        return;
    }

    const existingModal = document.getElementById('bomAssignmentModal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'bomAssignmentModal';
    modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:var(--bg-primary);display:flex;flex-direction:column;z-index:9999;';

    let html = '<div style="background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0;flex-wrap:wrap;gap:8px;">';
    html += `<h2 style="margin:0;color:#e6edf3;"><i class="fas fa-layer-group" style="color:#2a6df4;"></i> BOM Assignment - ${orderId}</h2>`;
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
    html += '<button class="btn btn-outline btn-sm" onclick="openModal(\'addRMItemModal\')" style="border-color:var(--border-color);color:var(--text-secondary);"><i class="fas fa-plus"></i> Item</button>';
    html += '<button class="btn btn-outline btn-sm" onclick="openSupplierModalForBOM()" style="border-color:var(--border-color);color:var(--text-secondary);"><i class="fas fa-plus"></i> Supplier</button>';
    html += '<button class="btn btn-success" onclick="saveBOMAssignment()"><i class="fas fa-save"></i> Save</button>';
    html += '<button class="btn btn-outline" onclick="closeBOMAssignment()">Close</button>';
    html += '</div></div>';

    html += '<div style="flex:1;overflow-y:auto;padding:20px 24px;background:var(--bg-primary);">';

    gridData.forEach((row, idx) => {
        const fgDesign = row[1] || 'Design' + (idx + 1);
        const fgColor = row[2] || 'Color' + (idx + 1);

        html += '<div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;margin-bottom:16px;overflow:hidden;">';
        html += `<div style="background:var(--table-header);padding:10px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--border-color);">`;
        html += `<span style="color:var(--text-primary);">FG ${idx + 1}: <span style="font-family:monospace;color:var(--nav-active-text);">${fgDesign}</span> | Color: ${fgColor}</span>`;
        html += `<span style="font-size:12px;color:var(--text-muted);">Sizes: ${sizes.join(', ')}</span>`;
        html += '</div>';

        html += '<div style="padding:12px;overflow-x:auto;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:var(--table-header);">';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Item No *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Item Name</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Color</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Size *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Cons/PC *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">UOM</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Size Sens</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Rate *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Supplier *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Lead *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid #30363d;text-align:left;color:#8b949e;width:30px;"></th>';
        html += '</tr></thead>';
        html += `<tbody id="bomRows-${idx}">`;
        for (let r = 0; r < 3; r++) {
            html += buildBOMRow(idx, r);
        }
        html += '</tbody></table>';
        html += `<button class="btn btn-outline btn-sm" onclick="addBOMRowToFG(${idx})" style="margin-top:8px;color:#58a6ff;border-color:#30363d;"><i class="fas fa-plus"></i> Add Row</button>`;
        html += '</div></div>';
    });

    html += '</div></div>';
    modal.innerHTML = html;
    document.body.appendChild(modal);

    setTimeout(() => {
        setupBOMAutocomplete();
        setTimeout(calculateBOMTotal, 300);
    }, 100);
}

function renderBOMModalWithExistingData(fgData) {
    const orderId = ERP_STATE.bomOrderId;
    const gridData = ERP_STATE.bomGridData || [];
    const sizes = ERP_STATE.bomSizes || [];

    if (!fgData || fgData.length === 0) {
        showToast('No BOM data found', 'error');
        return;
    }

    const existingModal = document.getElementById('bomAssignmentModal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'bomAssignmentModal';
    modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:var(--bg-primary);display:flex;flex-direction:column;z-index:9999;';

    let html = '<div style="background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0;flex-wrap:wrap;gap:8px;">';
    html += `<h2 style="margin:0;color:#e6edf3;"><i class="fas fa-layer-group" style="color:#2a6df4;"></i> Edit BOM - ${orderId}</h2>`;
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
    html += '<button class="btn btn-outline btn-sm" onclick="openModal(\'addRMItemModal\')" style="border-color:var(--border-color);color:var(--text-secondary);"><i class="fas fa-plus"></i> Item</button>';
    html += '<button class="btn btn-outline btn-sm" onclick="openSupplierModalForBOM()" style="border-color:var(--border-color);color:var(--text-secondary);"><i class="fas fa-plus"></i> Supplier</button>';
    html += '<button class="btn btn-success" onclick="saveBOMAssignment()"><i class="fas fa-save"></i> Save BOM</button>';
    html += '<button class="btn btn-outline" onclick="closeBOMAssignment()">Close</button>';
    html += '</div></div>';

    html += '<div style="flex:1;overflow-y:auto;padding:20px 24px;background:var(--bg-primary);">';

    fgData.forEach((fg, idx) => {
        const row = gridData[idx] || [];
        const fgDesign = row[1] || 'Design' + (idx + 1);
        const fgColor = row[2] || 'Color' + (idx + 1);
        const bomItems = fg.bomItems || [];

        html += '<div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;margin-bottom:16px;overflow:hidden;">';
        html += `<div style="background:var(--table-header);padding:10px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--border-color);">`;
        html += `<span style="color:var(--text-primary);">FG ${idx + 1}: <span style="font-family:monospace;color:var(--nav-active-text);">${fgDesign}</span> | Color: ${fgColor}</span>`;
        html += `<span style="font-size:12px;color:var(--text-muted);">Sizes: ${sizes.join(', ')}</span>`;
        html += '</div>';

        html += '<div style="padding:12px;overflow-x:auto;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:var(--table-header);">';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Item No *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Item Name</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Color</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Size *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Cons/PC *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">UOM</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Size Sens</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Rate *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Supplier *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid var(--border-color);text-align:left;color:var(--text-muted);">Lead *</th>';
        html += '<th style="padding:8px 6px;border-bottom:2px solid #30363d;text-align:left;color:#8b949e;width:30px;"></th>';
        html += '</tr></thead>';
        html += `<tbody id="bomRows-${idx}">`;

        if (bomItems.length > 0) {
            bomItems.forEach((item, itemIdx) => {
                html += buildPrefilledBOMRow(idx, itemIdx, item);
            });
        } else {
            for (let r = 0; r < 3; r++) {
                html += buildBOMRow(idx, r);
            }
        }
        html += '</tbody></table>';
        html += `<button class="btn btn-outline btn-sm" onclick="addBOMRowToFG(${idx})" style="margin-top:8px;color:#58a6ff;border-color:#30363d;"><i class="fas fa-plus"></i> Add Row</button>`;
        html += '</div></div>';
    });

    html += '</div></div>';
    modal.innerHTML = html;
    document.body.appendChild(modal);

    setTimeout(() => {
        setupBOMAutocomplete();
        setTimeout(calculateBOMTotal, 300);
    }, 100);
}

function buildBOMRow(fgIdx, rowIdx) {
    return `<tr>
        <td><input type="text" class="bom-item-no" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Type to search..." style="width:120px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-item-name" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Auto" readonly style="width:100px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-muted);font-size:13px;"></td>
        <td><input type="text" class="bom-color" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Auto" readonly style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-muted);font-size:13px;"></td>
        <td><input type="text" class="bom-size" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Size" style="width:70px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="number" class="bom-consumption" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="0" step="0.01" style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-uom" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Auto" readonly style="width:60px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-muted);font-size:13px;"></td>
        <td><select class="bom-size-sensitive" data-fg="${fgIdx}" data-row="${rowIdx}" style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"><option value="No">No</option><option value="Yes">Yes</option></select></td>
        <td><input type="number" class="bom-rate" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="0" step="0.01" style="width:90px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-supplier" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="Type to search..." style="width:130px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="number" class="bom-lead" data-fg="${fgIdx}" data-row="${rowIdx}" placeholder="0" style="width:70px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><button class="btn btn-danger btn-xs" onclick="removeBOMRow(this); setTimeout(calculateBOMTotal, 200);" style="background:transparent;border:none;color:#ea4335;cursor:pointer;font-size:18px;padding:2px 6px;">x</button></td>
    </tr>`;
}

function buildPrefilledBOMRow(fgIdx, rowIdx, item) {
    return `<tr>
        <td><input type="text" class="bom-item-no" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.item_no || ''}" placeholder="Type to search..." style="width:120px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-item-name" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.item_name || ''}" placeholder="Auto" style="width:100px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-color" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.item_color || ''}" placeholder="Auto" style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-size" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.item_size || ''}" placeholder="Size" style="width:70px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="number" class="bom-consumption" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.consumption || ''}" placeholder="0" step="0.01" style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-uom" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.uom || 'PCS'}" placeholder="UOM" style="width:60px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><select class="bom-size-sensitive" data-fg="${fgIdx}" data-row="${rowIdx}" style="width:80px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"><option value="No" ${item.size_sensitive === 'Yes' ? '' : 'selected'}>No</option><option value="Yes" ${item.size_sensitive === 'Yes' ? 'selected' : ''}>Yes</option></select></td>
        <td><input type="number" class="bom-rate" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.rate || ''}" placeholder="0" step="0.01" style="width:90px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="text" class="bom-supplier" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.supplier || ''}" placeholder="Type to search..." style="width:130px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><input type="number" class="bom-lead" data-fg="${fgIdx}" data-row="${rowIdx}" value="${item.leadtime || ''}" placeholder="0" style="width:70px;padding:4px 6px;border:1px solid var(--border-color);border-radius:4px;background:var(--bg-input);color:var(--text-primary);font-size:13px;"></td>
        <td><button class="btn btn-danger btn-xs" onclick="removeBOMRow(this); setTimeout(calculateBOMTotal, 200);" style="background:transparent;border:none;color:#ea4335;cursor:pointer;font-size:18px;padding:2px 6px;">x</button></td>
    </tr>`;
}

function addBOMRowToFG(fgIdx) {
    const tbody = document.getElementById('bomRows-' + fgIdx);
    if (!tbody) return;
    const rowCount = tbody.querySelectorAll('tr').length;
    const tr = document.createElement('tr');
    tr.innerHTML = buildBOMRow(fgIdx, rowCount);
    tbody.appendChild(tr);
    setTimeout(() => calculateBOMTotal(), 200);

    const newInput = tr.querySelector('.bom-item-no');
    if (newInput) {
        newInput.setAttribute('list', 'itemDatalist');
        newInput.addEventListener('blur', function() { autoFillBOMItem(this); });
        newInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') autoFillBOMItem(this); });
    }
    const supplierInput = tr.querySelector('.bom-supplier');
    if (supplierInput) {
        supplierInput.setAttribute('list', 'supplierDatalist');
    }
}

function closeBOMAssignment() {
    const modal = document.getElementById('bomAssignmentModal');
    if (modal) modal.remove();
    ERP_STATE.isBOMAssignmentOpen = false;
}

function openSupplierModalForBOM() {
    openModal('rmSupplierModal');
    setTimeout(() => {
        const modal = document.getElementById('rmSupplierModal');
        if (modal) {
            modal.style.zIndex = '10001';
            const box = modal.querySelector('.modal-box');
            if (box) box.style.zIndex = '10002';
        }
    }, 50);
}

async function saveBOMAssignment() {
    showToast('Saving BOM...', 'info');

    const fgBOMData = {};
    const fgRows = document.querySelectorAll('[id^="bomRows-"]');
    let valid = true;
    const validationErrors = [];
    const orderId = ERP_STATE.bomOrderId;
    const gridData = ERP_STATE.bomGridData || [];

    fgRows.forEach(tbody => {
        const fgIdx = tbody.id.replace('bomRows-', '');
        const idx = parseInt(fgIdx);
        const row = gridData[idx];
        if (!row) {
            validationErrors.push('FG index ' + fgIdx + ' not found in grid data');
            return;
        }
        const fgKey = orderId + '|' + (row[1] || 'Design' + (idx + 1)) + '|' + (row[2] || 'Color' + (idx + 1));
        const rows = tbody.querySelectorAll('tr');
        const items = [];
        rows.forEach((row, rowIdx) => {
            const itemNo = row.querySelector('.bom-item-no').value.trim();
            if (!itemNo) return;
            const itemName = row.querySelector('.bom-item-name').value.trim() || itemNo;
            const color = row.querySelector('.bom-color').value.trim() || '';
            const size = row.querySelector('.bom-size').value.trim();
            const consumption = parseFloat(row.querySelector('.bom-consumption').value) || 0;
            const uom = row.querySelector('.bom-uom').value.trim() || 'PCS';
            const sizeSensitive = row.querySelector('.bom-size-sensitive').value || 'No';
            const rate = parseFloat(row.querySelector('.bom-rate').value) || 0;
            const supplier = row.querySelector('.bom-supplier').value.trim();
            const lead = parseFloat(row.querySelector('.bom-lead').value) || 0;

            if (!itemNo || !size || consumption <= 0 || rate <= 0 || !supplier || lead <= 0) {
                valid = false;
                let errMsg = 'FG ' + fgIdx + ' Row ' + rowIdx + ': ';
                if (!itemNo) errMsg += 'Item No required, ';
                if (!size) errMsg += 'Size required, ';
                if (consumption <= 0) errMsg += 'Consumption > 0 required, ';
                if (rate <= 0) errMsg += 'Rate > 0 required, ';
                if (!supplier) errMsg += 'Supplier required, ';
                if (lead <= 0) errMsg += 'Lead > 0 required';
                validationErrors.push(errMsg);
                return;
            }
            items.push({
                item_no: itemNo,
                item_name: itemName,
                item_color: color,
                item_size: size,
                consumption: consumption,
                uom: uom,
                size_sensitive: sizeSensitive,
                rate: rate,
                supplier: supplier,
                leadtime: lead,
                cgst: 0,
                igst: 0,
                hsn: ''
            });
        });
        if (items.length) {
            fgBOMData[fgKey] = items;
        }
    });

    if (!valid) {
        showToast('Please fix validation errors: ' + validationErrors.join('; '), 'error');
        return;
    }
    if (Object.keys(fgBOMData).length === 0) {
        showToast('No BOM items to save. Please add at least one item row with valid data.', 'error');
        return;
    }

    try {
        await API.processToBom(orderId);
        console.log("Token moved to BOM stage for order:", orderId);
    } catch (e) {
        console.warn("Token already at BOM or error:", e.message);
    }

    try {
        const response = await fetch('/bom/save-order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({
                buyer_order_id: orderId,
                fg_bom_data: fgBOMData
            })
        });
        const result = await response.json();
        if (result.success) {
            showToast(result.message, 'success');
            closeBOMAssignment();
            refreshBuyerOrders();
            setTimeout(() => {
                refreshBOMOrders();
                const bomTab = document.querySelector('[data-module="BOM_COSTING"]');
                if (bomTab) bomTab.click();
            }, 500);
        } else {
            showToast('Error saving BOM: ' + result.message, 'error');
        }
    } catch (e) {
        showToast('Error saving BOM: ' + e.message, 'error');
    }
}

async function submitBOMForApproval(orderId) {
    if (!confirm(`[WARN] Are you sure you want to submit BOM for ${orderId} for approval?\nThis will move the order to Costing Approval stage.`)) return;
    showToast('Submitting for approval...', 'info');
    try {
        const response = await fetch('/bom/submit-approval', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ buyer_order_id: orderId })
        });
        const result = await response.json();
        if (result.success) {
            showToast(result.message, 'success');
            refreshBOMOrders();
            refreshApprovalOrders();
            const approvalTab = document.querySelector('[data-module="COSTING_APPROVAL"]');
            if (approvalTab) approvalTab.click();
        } else {
            showToast('Error: ' + result.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 12: STAGE 2 - COSTING APPROVAL
// ==============================================================


// ==============================================================
// SECTION 13: STAGE 3 - RM ORDER (PO)
// ==============================================================

async function refreshRMOrders() {
    showToast('Loading RM orders...', 'info');
    try {
        const orders = await API.getRMOrders();
        ERP_STATE.rmOrdersData = orders || [];
        renderRMOrders(ERP_STATE.rmOrdersData);
        showToast(ERP_STATE.rmOrdersData && ERP_STATE.rmOrdersData.length ? 'RM orders loaded' : 'No RM orders found', ERP_STATE.rmOrdersData && ERP_STATE.rmOrdersData.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading RM orders: ' + e.message, 'error');
    }
}

function renderRMOrders(orders) {
    const container = document.getElementById("rmOrderContainer");

    var html = '<div class="table-wrap"><table style="width:100%;border-collapse:collapse;">';
    html += '<thead><tr style="background:var(--table-header);">';
    html += '<th style="padding:8px 12px;text-align:left;">Order ID</th>';
    html += '<th style="padding:8px 12px;text-align:left;">Buyer</th>';
    html += '<th style="padding:8px 12px;text-align:left;">Buyer Order No</th>';
    html += '<th style="padding:8px 12px;text-align:left;">Order Date</th>';
    html += '<th style="padding:8px 12px;text-align:center;">No of FGs</th>';
    html += '<th style="padding:8px 12px;text-align:center;">No of POs Made</th>';
    html += '<th style="padding:8px 12px;text-align:center;">Status</th>';
    html += '<th style="padding:8px 12px;text-align:center;">Actions</th>';
    html += '</tr></thead><tbody>';

    if (!orders || orders.length === 0) {
        html += '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No orders in RM Order stage.</td></tr>';
    } else {
        orders.forEach(function(order) {
            var statusBadge = 'info';
            if (order.status === 'RM_ORDER') statusBadge = 'info';
            else if (order.status === 'PROCESSED') statusBadge = 'success';
            else if (order.status === 'CANCELLED') statusBadge = 'danger';

            html += '<tr>';
            html += '<td style="padding:8px 12px;"><strong>' + (order.buyerOrderId || 'N/A') + '</strong></td>';
            html += '<td style="padding:8px 12px;">' + (order.buyerName || 'Unknown') + '</td>';
            html += '<td style="padding:8px 12px;">' + (order.buyerOrderNo || 'N/A') + '</td>';
            html += '<td style="padding:8px 12px;">' + (order.orderDate ? new Date(order.orderDate).toLocaleDateString('en-IN') : '—') + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;"><span class="badge-status info">' + (order.totalFGs || 0) + '</span></td>';
            html += '<td style="padding:8px 12px;text-align:center;"><span class="badge-status info">' + (order.totalPOsMade || 0) + '</span></td>';
            html += '<td style="padding:8px 12px;text-align:center;"><span class="badge-status ' + statusBadge + '">' + (order.totalSuppliers ? order.processedSuppliers + '/' + order.totalSuppliers + ' suppliers done' : (order.status || 'RM_ORDER')) + '</span></td>';
            html += '<td style="padding:8px 12px;text-align:center;">';
            html += '<button class="btn btn-success btn-sm" onclick="viewRMMaterials(\'' + order.buyerOrderId + '\')" title="Process to Inspection"><i class="fas fa-check"></i> Process</button> ';
            html += '<button class="btn btn-danger btn-sm" onclick="cancelRMOrderFromCard(\'' + order.buyerOrderId + '\')"><i class="fas fa-undo"></i> Cancel</button>';
            html += '</td></tr>';
        });
    }

    html += '</tbody></table></div>';
    container.innerHTML = html;
    var countEl = document.getElementById("rmOrderCount");
    if (countEl) countEl.textContent = orders ? orders.length : 0;
}

// ==============================================================
// RM PROCESS MODAL FUNCTIONS
// ==============================================================


async function confirmProcessRMOrder() {
    const orderId = window._rmOrderId;
    if (!orderId) return;
    if (!confirm('Confirm processing RM Order ' + orderId + '?')) return;

    showToast('Processing...', 'info');
    try {
        const response = await fetch('/rm-order/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ po_token: orderId })
        });
        const result = await response.json();
        if (result.success) {
            showToast(result.message, 'success');
            document.getElementById('rmProcessModal').remove();
            refreshRMOrders();
        } else {
            showToast('Error: ' + result.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function openProcessPOModal(supplier) {
    const supplierData = ERP_STATE.rmOrdersData.find(o => o.supplier === supplier);
    if (!supplierData) {
        showToast('Supplier not found', 'error');
        return;
    }
    ERP_STATE.currentSupplierItems = supplierData.items || [];
    ERP_STATE.selectedGroups = new Set();
    ERP_STATE.groupMap = {};
    ERP_STATE.groupItemsMap = {};

    ERP_STATE.currentSupplierItems.forEach(item => {
        const aggKey = `${item.itemName}|${item.garmentSize || 'ALL'}|${item.color || ''}|${item.itemSize || ''}`;
        if (!ERP_STATE.groupMap[aggKey]) {
            ERP_STATE.groupMap[aggKey] = {
                itemNo: item.itemNo,
                itemName: item.itemName,
                garmentSize: item.garmentSize || 'ALL',
                color: item.color || '',
                itemSize: item.itemSize || '',
                totalBalance: 0,
                uom: item.uom || 'PCS',
                rate: item.rate || 0,
                cgst: item.cgst || 0,
                igst: item.igst || 0,
                hsn: item.hsn || '',
                fgKeys: [],
                originalIndices: []
            };
            ERP_STATE.groupItemsMap[aggKey] = [];
        }
        ERP_STATE.groupMap[aggKey].totalBalance += (item.balanceToOrder || item.requiredQty || 0);
        ERP_STATE.groupMap[aggKey].fgKeys.push(item.fgKey);
        ERP_STATE.groupMap[aggKey].originalIndices.push(ERP_STATE.currentSupplierItems.indexOf(item));
        ERP_STATE.groupItemsMap[aggKey].push(item);
    });

    Object.keys(ERP_STATE.groupMap).forEach(key => ERP_STATE.selectedGroups.add(key));
    document.getElementById('poModalSupplier').innerHTML = `Supplier: <strong>${supplier}</strong>`;
    document.getElementById('poModalItemCount').innerHTML = `Aggregated Items: <strong>${Object.keys(ERP_STATE.groupMap).length}</strong>`;
    document.getElementById('poSummary').textContent = '';
    document.getElementById('selectedCount').textContent = '0';
    document.getElementById('supplierAlias').value = supplier;
    renderPOItems();
    updatePOItemCount();
    document.getElementById('processPOModal').classList.add('active');
}

function renderPOItems() {
    const tb = document.getElementById('poItemsBody');
    const groupKeys = Object.keys(ERP_STATE.groupMap);
    if (groupKeys.length === 0) {
        tb.innerHTML = '<tr><td colspan="12" style="text-align:center;color:#62748e;">No items</td></tr>';
        return;
    }
    let html = '';
    groupKeys.forEach(aggKey => {
        const group = ERP_STATE.groupMap[aggKey];
        const isSelected = ERP_STATE.selectedGroups.has(aggKey);
        const cgst = group.cgst || 0;
        const igst = group.igst || 0;
        const balance = group.totalBalance;
        const fgKeysDisplay = group.fgKeys.join(', ');
        html += `<tr>
            <td><input type="checkbox" class="group-checkbox" data-group="${aggKey}" ${isSelected ? 'checked' : ''} onchange="toggleGroup('${aggKey}')"></td>
            <td style="font-size:8px;color:#62748e;">${fgKeysDisplay}</td>
            <td>${group.itemNo || ''}</td>
            <td>${group.itemName || ''}</td>
            <td>${group.garmentSize || 'ALL'}</td>
            <td>${group.itemSize || ''}</td>
            <td>${group.color || ''}</td>
            <td>${balance.toFixed(2)}</td>
            <td>${group.uom || 'PCS'}</td>
            <td>Rs.${(group.rate || 0).toFixed(2)}</td>
            <td><input type="number" class="group-cgst" data-group="${aggKey}" value="${cgst}" step="0.01" style="width:40px;" onchange="updateGroupCGST('${aggKey}', this.value)"></td>
            <td><input type="number" class="group-igst" data-group="${aggKey}" value="${igst}" step="0.01" style="width:40px;" onchange="updateGroupIGST('${aggKey}', this.value)"></td>
        </tr>`;
    });
    tb.innerHTML = html;
    document.getElementById('poModalItemCount').innerHTML = `Aggregated Items: <strong>${groupKeys.length}</strong>`;
    updatePOItemCount();
}

function toggleGroup(aggKey) {
    if (ERP_STATE.selectedGroups.has(aggKey)) {
        ERP_STATE.selectedGroups.delete(aggKey);
    } else {
        ERP_STATE.selectedGroups.add(aggKey);
    }
    const cb = document.querySelector(`.group-checkbox[data-group="${aggKey}"]`);
    if (cb) cb.checked = ERP_STATE.selectedGroups.has(aggKey);
    updatePOItemCount();
}

function toggleAllItems() {
    const checked = document.getElementById('selectAllItems').checked;
    const groupKeys = Object.keys(ERP_STATE.groupMap);
    groupKeys.forEach(key => {
        if (checked) ERP_STATE.selectedGroups.add(key);
        else ERP_STATE.selectedGroups.delete(key);
    });
    document.querySelectorAll('.group-checkbox').forEach(cb => { cb.checked = checked; });
    updatePOItemCount();
}

function updateGroupCGST(aggKey, value) {
    const cgst = parseFloat(value) || 0;
    if (ERP_STATE.groupMap[aggKey]) {
        ERP_STATE.groupMap[aggKey].cgst = cgst;
        const items = ERP_STATE.groupItemsMap[aggKey] || [];
        items.forEach(item => { item.cgst = cgst; });
    }
}

function updateGroupIGST(aggKey, value) {
    const igst = parseFloat(value) || 0;
    if (ERP_STATE.groupMap[aggKey]) {
        ERP_STATE.groupMap[aggKey].igst = igst;
        const items = ERP_STATE.groupItemsMap[aggKey] || [];
        items.forEach(item => { item.igst = igst; });
    }
}

function updatePOItemCount() {
    const count = ERP_STATE.selectedGroups.size;
    const selectedCountEl = document.getElementById('selectedCount');
    if (selectedCountEl) selectedCountEl.textContent = count;
    let totalQty = 0;
    ERP_STATE.selectedGroups.forEach(aggKey => {
        if (ERP_STATE.groupMap[aggKey]) {
            totalQty += ERP_STATE.groupMap[aggKey].totalBalance || 0;
        }
    });
    const poSummary = document.getElementById('poSummary');
    if (poSummary) poSummary.textContent = `${count} groups · Total Qty: ${totalQty.toFixed(2)} units`;
}

function updatePOItems() { updatePOItemCount(); }

function closeProcessPOModal() {
    document.getElementById('processPOModal').classList.remove('active');
    ERP_STATE.currentSupplierItems = [];
    ERP_STATE.selectedGroups = new Set();
    ERP_STATE.groupMap = {};
    ERP_STATE.groupItemsMap = {};
}

async function generatePO() {
    const supplier = document.getElementById('poModalSupplier').textContent.replace('Supplier: ', '').trim();
    if (!supplier) {
        showToast('Please select a supplier', 'error');
        return;
    }
    const supplierAlias = document.getElementById('supplierAlias').value.trim() || supplier;
    const selectedItemsList = [];
    ERP_STATE.selectedGroups.forEach(aggKey => {
        const items = ERP_STATE.groupItemsMap[aggKey] || [];
        items.forEach(item => {
            selectedItemsList.push({ ...item, orderedQty: item.balanceToOrder || item.requiredQty || 0 });
        });
    });
    if (selectedItemsList.length === 0) {
        showToast('Please select at least one group', 'error');
        return;
    }
    const excess = parseFloat(document.getElementById('poExcess').value) || 0;
    const allowExtra = document.getElementById('allowExtra').checked;
    const cgstOverride = {};
    const igstOverride = {};
    selectedItemsList.forEach(item => {
        if (item.requirementKey) {
            const groupKey = `${item.itemName}|${item.garmentSize || 'ALL'}|${item.color || ''}|${item.itemSize || ''}`;
            cgstOverride[item.requirementKey] = ERP_STATE.groupMap[groupKey]?.cgst || item.cgst || 0;
            igstOverride[item.requirementKey] = ERP_STATE.groupMap[groupKey]?.igst || item.igst || 0;
        }
    });
    const poData = {
        supplier,
        supplier_alias: supplierAlias,
        selected_items: selectedItemsList,
        excess_percentage: excess,
        cgst_override: cgstOverride,
        igst_override: igstOverride,
        allow_extra: allowExtra
    };
    showToast('Generating PO...', 'info');
    const btn = document.getElementById('generatePOBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
    try {
        const r = await API.generatePO(poData);
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-file-pdf"></i> Generate PO';
        if (r.success) {
            showToast(`PO generated with ${r.itemCount} items`, 'success');
            openPOPreview(r.poHTML, r.poToken);
            closeProcessPOModal();
            refreshRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-file-pdf"></i> Generate PO';
        showToast('Error: ' + e.message, 'error');
    }
}

function openPOPreview(html, poToken) {
    ERP_STATE.currentPOToken = poToken;
    document.getElementById('poPreviewToken').textContent = poToken;
    document.getElementById('poPreviewFrame').srcdoc = html;
    document.getElementById('poPreviewModal').classList.add('active');
}

function closePOPreview() {
    document.getElementById('poPreviewModal').classList.remove('active');
    document.getElementById('poPreviewFrame').srcdoc = '';
    ERP_STATE.currentPOToken = null;
}

async function savePOAction() {
    if (!ERP_STATE.currentPOToken) {
        showToast('No PO to save', 'error');
        return;
    }
    showToast('Saving PO...', 'info');
    try {
        const r = await API.savePO(ERP_STATE.currentPOToken);
        if (r.success) {
            showToast('PO saved!', 'success');
            closePOPreview();
            refreshRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function processPOFromPreview() {
    if (!ERP_STATE.currentPOToken) {
        showToast('No PO to process', 'error');
        return;
    }
    if (!confirm('Process this PO?')) return;
    showToast('Processing PO...', 'info');
    try {
        const r = await API.processPO(ERP_STATE.currentPOToken);
        if (r.success) {
            showToast('PO processed! Moved to GRN.', 'success');
            closePOPreview();
            refreshRMOrders();
            refreshGRNOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 14: STAGE 4 - RM INSPECTION
// ==============================================================

async function refreshRMInspections() {
    showToast('Loading RM inspections...', 'info');
    try {
        const data = await API.getRMInspections();
        renderRMInspections(data);
        const countEl = document.getElementById('rmInspectionCount');
        if (countEl) countEl.textContent = data ? data.length : 0;
        showToast(data && data.length ? 'RM inspections loaded' : 'No RM inspections found', data && data.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading RM inspections: ' + e.message, 'error');
    }
}

function renderRMInspections(groups) {
    const tb = document.getElementById('rmInspectionBody');
    if (!tb) return;

    if (!groups || groups.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No RM inspections found.</td></tr>';
        return;
    }

    let html = '';
    groups.forEach(grp => {
        const boId = grp.buyerOrderId || '—';
        const allMade = grp.allPOsMade === true;

        // Buyer-order group header row
        html += `<tr style="background:var(--table-header);">
            <td colspan="8" style="padding:8px 12px;">
                <strong>${boId}</strong>
                <span class="text-muted" style="margin-left:8px;">${grp.buyerName || ''} · Order No: ${grp.buyerOrderNo || 'N/A'}</span>
                <span class="badge-status ${allMade ? 'success' : 'warning'}" style="margin-left:8px;">
                    POs made: ${grp.totalPOsMade}/${grp.totalRequiredSuppliers}
                </span>
                ${allMade ? '' : '<span class="text-warning" style="margin-left:8px;font-weight:600;">Complete all POs</span>'}
            </td>
        </tr>`;

        (grp.pos || []).forEach(insp => {
            const statusBadge = insp.status === 'PASSED' ? 'success' :
                               (insp.status === 'REJECTED' ? 'danger' : 'warning');
            const firstItem = insp.items && insp.items.length > 0 ? insp.items[0] : {};
            const totalQty = insp.items ? insp.items.reduce((sum, i) => sum + (parseFloat(i.orderedQty) || 0), 0) : 0;
            const isPassed = insp.status === 'PASSED';
            const isRejected = insp.status === 'REJECTED';
            const poToken = insp.poToken || '';

            // Pass/Fail enabled only when all POs made
            const passDisabled = !allMade || isPassed;
            const failDisabled = !allMade || isPassed || isRejected;

            html += `<tr>
                <td>${boId}</td>
                <td>${poToken}</td>
                <td>${insp.supplier || '—'}</td>
                <td>${firstItem.itemName || '—'}</td>
                <td>${totalQty.toFixed(2)}</td>
                <td>${insp.itemCount || 0}</td>
                <td><span class="badge-status ${statusBadge}">${insp.status || 'PENDING'}</span>
                    ${insp.observation ? '<div class="text-muted" style="font-size:11px;margin-top:2px;">' + insp.observation + '</div>' : ''}
                </td>
                <td>
                    <button class="btn btn-success btn-xs" onclick="passRMInspection('${poToken}')" ${passDisabled ? 'disabled' : ''} title="${allMade ? '' : 'Complete all POs'}">
                        <i class="fas fa-check"></i> Pass
                    </button>
                    <button class="btn btn-danger btn-xs" onclick="failRMInspection('${poToken}')" ${failDisabled ? 'disabled' : ''} title="${allMade ? '' : 'Complete all POs'}">
                        <i class="fas fa-times"></i> Fail
                    </button>
                    <button class="btn btn-outline btn-xs" onclick="setRMInspectionObservation('${poToken}')" title="Add / edit observation">
                        <i class="fas fa-comment"></i> Note
                    </button>
                    <button class="btn btn-info btn-xs" onclick="printPOForRow('${poToken}')" title="Print RM PO">
                        <i class="fas fa-print"></i> Print
                    </button>
                </td>
            </tr>`;
        });
    });
    tb.innerHTML = html;
}

function setRMInspectionObservation(poToken) {
    if (!poToken) return;
    const obs = prompt('Observation / comments for PO ' + poToken + ':');
    if (obs === null) return;
    API.call('/rm-inspection/set-observation', 'POST', { po_token: poToken, observation: obs })
        .then(r => {
            if (r.success) { showToast('Observation saved', 'success'); refreshRMInspections(); }
            else { showToast('Error: ' + r.message, 'error'); }
        })
        .catch(e => showToast('Error: ' + e.message, 'error'));
}

async function cancelRMInspectionOrder(buyerOrderId) {
    if (!buyerOrderId) { showToast('No buyer order loaded', 'error'); return; }
    if (!confirm('Cancel RM Inspection for this buyer order?\nThis will move the order back to RM Order stage.')) return;
    showToast('Cancelling RM Inspection...', 'info');
    try {
        const r = await API.call('/rm-inspection/cancel', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || 'RM Inspection cancelled', 'success');
            refreshRMInspections();
            refreshRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function passRMInspection(poToken) {
    if (!confirm(`Pass RM Inspection for PO: ${poToken}?`)) return;
    showToast('Processing...', 'info');
    try {
        const r = await API.call('/rm-inspection/pass', 'POST', { po_token: poToken });
        if (r.success) {
            showToast(r.message, 'success');
            refreshRMInspections();
            refreshGRNOrders();
            refreshRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function failRMInspection(poToken) {
    if (!confirm(`Fail RM Inspection for PO: ${poToken}?`)) return;
    showToast('Processing...', 'info');
    try {
        const r = await API.call('/rm-inspection/fail', 'POST', { po_token: poToken });
        if (r.success) {
            showToast(r.message, 'success');
            refreshRMInspections();
            refreshRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 15: STAGE 5 - GRN
// ==============================================================

async function refreshGRNOrders() {
    showToast('Loading GRN orders...', 'info');
    try {
        const orders = await API.getGRNBuyerOrders();
        ERP_STATE.grnData = orders || [];
        renderGRNOrders(ERP_STATE.grnData);
        const countEl = document.getElementById('grnCount');
        if (countEl) countEl.textContent = ERP_STATE.grnData ? ERP_STATE.grnData.length : 0;
        showToast(ERP_STATE.grnData && ERP_STATE.grnData.length ? 'GRN orders loaded' : 'No GRN orders found', ERP_STATE.grnData && ERP_STATE.grnData.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading GRN orders: ' + e.message, 'error');
    }
}

function renderGRNOrders(orders) {
    const tb = document.getElementById('grnOrderBody');
    if (!tb) return;

    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No GRN orders found.</td></tr>';
        return;
    }

    let html = '';
    orders.forEach(order => {
        const statusBadge = order.status === 'PARTIAL' ? 'partial' : (order.status === 'COMPLETED' ? 'success' : 'info');
        const statusText = order.status || 'PENDING';
        const orderId = order.buyerOrderId || order.buyer_order_id || '—';
        const hasAnyGRN = order.hasAnyGRN === true;
        // Q4: Cancel at buyer-order level is a pre-receive exit. It is only
        // enabled while NO PO of this buyer order has been GRNed yet.
        const cancelDisabled = hasAnyGRN;

        html += `<tr>
            <td><strong>${orderId}</strong></td>
            <td>${order.buyerName || order.buyer_name || '—'}</td>
            <td>${order.buyerOrderNo || order.buyer_order_no || '—'}</td>
            <td>${safeDate(order.orderDate || order.order_date)}</td>
            <td><span class="badge-status info">${order.totalFGs || order.total_fgs || 0}</span></td>
            <td><span class="badge-status info">${order.totalPOs || order.total_pos || 0}</span></td>
            <td><span class="badge-status ${statusBadge}">${statusText}</span></td>
            <td>
                <button class="btn btn-primary btn-sm" onclick="openGRNPOListModal('${orderId}')">
                    <i class="fas fa-list"></i> View POs
                </button>
                <button class="btn btn-danger btn-sm" onclick="cancelGRNBuyerOrder('${orderId}')" ${cancelDisabled ? 'disabled' : ''} title="${cancelDisabled ? 'Cannot cancel: at least one PO has been GRNed' : 'Cancel buyer order at GRN stage'}">
                    <i class="fas fa-undo"></i> Cancel
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

async function cancelGRNBuyerOrder(buyerOrderId) {
    if (!buyerOrderId) return;
    if (!confirm('Cancel buyer order ' + buyerOrderId + ' at GRN stage?\nThis moves the buyer order back to RM Order and no stock was received yet.')) return;
    showToast('Cancelling buyer order at GRN...', 'info');
    try {
        const r = await API.call('/grn/cancel-buyer-order', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || 'Buyer order cancelled', 'success');
            refreshGRNOrders();
            refreshRMOrders();
            refreshRMInspections();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function openGRNPOListModal(orderId) {
    if (!orderId) return;
    window._grnPOParentOrderId = orderId;
    document.getElementById('grnPOListOrderId').textContent = orderId;

    // Populate buyer info from ERP_STATE.grnData
    const buyerOrder = (ERP_STATE.grnData || []).find(o => (o.buyerOrderId || o.buyer_order_id) === orderId);
    if (buyerOrder) {
        document.getElementById('grnPOListBuyerName').textContent = buyerOrder.buyerName || buyerOrder.buyer_name || '—';
        document.getElementById('grnPOListBuyerOrderNo').textContent = buyerOrder.buyerOrderNo || buyerOrder.buyer_order_no || '—';
    } else {
        document.getElementById('grnPOListBuyerName').textContent = '—';
        document.getElementById('grnPOListBuyerOrderNo').textContent = '—';
    }

    const tb = document.getElementById('grnPOListBody');
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">Loading POs...</td></tr>';
    document.getElementById('grnPOListModal').classList.add('active');

    try {
        const orderPOs = await API.getGRNOrdersByBuyer(orderId);

        if (!orderPOs || orderPOs.length === 0) {
            tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">No POs found for this order.</td></tr>';
            return;
        }

        let html = '';
        orderPOs.forEach(po => {
            const poToken = po.poToken || po.po_token || '—';
            const supplier = po.supplierAlias || po.supplier_alias || po.supplier || '—';
            const itemCount = po.items ? po.items.length : 0;
            const totalOrdered = parseFloat(po.totalOrdered) || 0;
            const totalAmount = totalOrdered * (po.items && po.items[0] ? (parseFloat(po.items[0].rate) || 0) : 0);
            
            // Use displayStatus: NR / PARTIAL / RECEIVED
            const displayStatus = po.displayStatus || 'NR';
            let statusBadge = 'info';
            if (displayStatus === 'RECEIVED') statusBadge = 'success';
            else if (displayStatus === 'PARTIAL') statusBadge = 'partial';
            else statusBadge = 'danger';  // NR = red to signal pending

            const isReceived = displayStatus === 'RECEIVED';
            const canClose = displayStatus === 'PARTIAL' || displayStatus === 'RECEIVED';

            html += `<tr>
                <td><strong>${poToken}</strong></td>
                <td>${supplier}</td>
                <td>${itemCount}</td>
                <td>${totalOrdered.toFixed(2)}</td>
                <td>₹${totalAmount.toFixed(2)}</td>
                <td><span class="badge-status ${statusBadge}">${displayStatus}</span></td>
                <td>
                    <button class="btn btn-primary btn-xs" onclick="printPOForRow('${poToken}')" title="Print PO">
                        <i class="fas fa-print"></i> Print
                    </button>
                    <button class="btn btn-success btn-xs" onclick="exportPOToExcel('${poToken}')" title="Export to Excel">
                        <i class="fas fa-file-excel"></i> Excel
                    </button>
                    <button class="btn btn-warning btn-xs" onclick="openGRNInwardModal('${poToken}', '${orderId}')" ${isReceived ? 'disabled' : ''}>
                        <i class="fas fa-clipboard-check"></i> Receive
                    </button>
                    <button class="btn btn-danger btn-xs" onclick="closeGRNPO('${poToken}', '${orderId}')" ${canClose ? '' : 'disabled'} title="${canClose ? 'Close this PO as RECEIVED' : 'Receive something first'}">
                        <i class="fas fa-lock"></i> Close PO
                    </button>
                </td>
            </tr>`;
        });
        tb.innerHTML = html;
    } catch (e) {
        tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

async function exportPOToExcel(poToken) {
    if (!poToken) return;
    try {
        // Find the PO in already-loaded data
        const allPOs = await API.getGRNOrdersByBuyer(window._grnPOParentOrderId || '');
        let po = null;
        for (const p of (allPOs || [])) {
            if ((p.poToken || p.po_token) === poToken) { po = p; break; }
        }
        if (!po) {
            // fallback: fetch without filter
            const all = await API.getGRNOrders();
            po = (all || []).find(p => (p.poToken || p.po_token) === poToken);
        }
        if (!po || !po.items || po.items.length === 0) {
            showToast('No PO data available for export', 'error');
            return;
        }

        // Filter junk items (empty itemNo AND zero orderedQty)
        const cleanItems = po.items.filter(item => {
            const itemNo = (item.itemNo || '').trim();
            const ordered = parseFloat(item.orderedQty) || 0;
            return itemNo !== '' || ordered > 0;
        });

        if (cleanItems.length === 0) {
            showToast('No valid items to export', 'error');
            return;
        }

        const rows = cleanItems.map((item, idx) => ({
            '#': idx + 1,
            'Item No': item.itemNo || '',
            'Item Name': item.itemName || '',
            'Garment Size': item.garmentSize || 'ALL',
            'Item Size': item.itemSize || '',
            'Color': item.color || '',
            'HSN': item.hsn || '',
            'Ordered Qty': parseFloat(item.orderedQty) || 0,
            'UOM': item.uom || 'PCS',
            'Rate': parseFloat(item.rate) || 0,
            'CGST%': parseFloat(item.cgst) || 0,
            'IGST%': parseFloat(item.igst) || 0,
            'Amount': ((parseFloat(item.orderedQty) || 0) * (parseFloat(item.rate) || 0)).toFixed(2)
        }));

        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, poToken.substring(0, 30));
        XLSX.writeFile(wb, poToken + '.xlsx');
        showToast('Excel downloaded', 'success');
    } catch (e) {
        showToast('Excel export failed: ' + e.message, 'error');
    }
}

function printPOForRow(poToken) {
    if (!poToken) return;
    window.open('/grn/print-po/' + encodeURIComponent(poToken), '_blank');
}

function closeGRNPOListModal() {
    document.getElementById('grnPOListModal').classList.remove('active');
}

async function closeGRNPO(poToken, orderId) {
    if (!poToken) return;
    if (!confirm('Close PO ' + poToken + ' as RECEIVED?\nEvery line must be at least 80% received. Remaining balance becomes a shortfall.')) return;
    showToast('Closing PO...', 'info');
    try {
        const r = await API.call('/grn/close-po', 'POST', { po_token: poToken });
        if (r.success) {
            showToast(r.message || 'PO closed', 'success');
            // Re-render the PO list so the status flips to RECEIVED.
            openGRNPOListModal(orderId);
            refreshGRNOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function openGRNInwardModal(poToken, orderId) {
    document.getElementById('grnInwardPOToken').textContent = poToken;
    document.getElementById('grnInwardInvoiceNo').value = '';
    document.getElementById('grnInwardReceivedDate').value = new Date().toISOString().split('T')[0];
    document.getElementById('grnInwardSupplier').value = 'Loading...';
    document.getElementById('grnInwardItemCount').value = '...';

    const tb = document.getElementById('grnInwardBody');
    tb.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-muted);padding:16px;">Loading PO items...</td></tr>';
    document.getElementById('grnInwardModal').classList.add('active');

    try {
        const poList = await API.getGRNOrdersByBuyer(orderId);
        const po = (poList || []).find(p => (p.poToken || p.po_token) === poToken);
        if (!po || !po.items || po.items.length === 0) {
            tb.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-muted);padding:16px;">No items found for this PO.</td></tr>';
            return;
        }

        // FILTER: Remove junk rows (empty itemNo AND zero orderedQty)
        const cleanItems = po.items.filter(item => {
            const itemNo = (item.itemNo || '').trim();
            const ordered = parseFloat(item.orderedQty) || 0;
            return itemNo !== '' || ordered > 0;
        });

        if (cleanItems.length === 0) {
            tb.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-muted);padding:16px;">No valid items found for this PO.</td></tr>';
            return;
        }

        // Update PO with clean items
        po.items = cleanItems;

        document.getElementById('grnInwardSupplier').value = po.supplierAlias || po.supplier || '—';
        document.getElementById('grnInwardItemCount').value = cleanItems.length;

        // Sum up already-received quantities from GRN RECEIVED entries
        // (we'll compute this in backend, but for now display ordered qty as received default)
        let html = '';
        cleanItems.forEach((item, idx) => {
            const ordered = parseFloat(item.orderedQty) || 0;
            const rate = parseFloat(item.rate) || 0;
            const received = parseFloat(item.receivedQty) || 0; // already received in previous inward
            const pending = Math.max(0, ordered - received);
            html += `<tr data-idx="${idx}">
                <td style="text-align:center;">${idx + 1}</td>
                <td style="text-align:left;">${item.itemNo || '—'}</td>
                <td style="text-align:left;">${item.itemName || '—'}</td>
                <td style="text-align:center;">${item.garmentSize || 'ALL'}</td>
                <td style="text-align:center;">${item.itemSize || ''}</td>
                <td style="text-align:center;">${item.color || ''}</td>
                <td style="text-align:center;">${item.hsn || ''}</td>
                <td style="text-align:right;" class="grn-ordered-qty">${ordered.toFixed(2)}</td>
                <td style="text-align:center;">${item.uom || 'PCS'}</td>
                <td style="text-align:right;"><input type="number" class="grn-inward-qty" data-idx="${idx}" value="${pending.toFixed(2)}" step="0.01" min="0" style="width:100px;text-align:right;" oninput="recalcGRNInwardRow(this)"></td>
                <td style="text-align:right;" class="grn-shortage">0.00</td>
                <td style="text-align:right;" class="grn-rate">${rate.toFixed(2)}</td>
                <td style="text-align:right;" class="grn-amount">${(pending * rate).toFixed(2)}</td>
            </tr>`;
        });
        tb.innerHTML = html;

        // Store PO reference for save
        window._grnInwardPO = po;
        window._grnInwardOrderId = orderId;

        // Recalc all rows initially
        document.querySelectorAll('#grnInwardBody .grn-inward-qty').forEach(inp => recalcGRNInwardRow(inp));
    } catch (e) {
        tb.innerHTML = '<tr><td colspan="13" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

function recalcGRNInwardRow(input) {
    const row = input.closest('tr');
    if (!row) return;
    const ordered = parseFloat(row.querySelector('.grn-ordered-qty').textContent) || 0;
    const rate = parseFloat(row.querySelector('.grn-rate').textContent) || 0;
    const received = parseFloat(input.value) || 0;
    const shortage = Math.max(0, ordered - received);
    const amount = received * rate;
    row.querySelector('.grn-shortage').textContent = shortage.toFixed(2);
    row.querySelector('.grn-amount').textContent = amount.toFixed(2);
}

async function saveGRNInward(isFinal) {
    isFinal = isFinal === true;
    const po = window._grnInwardPO;
    const orderId = window._grnInwardOrderId;
    if (!po || !orderId) {
        showToast('PO data missing', 'error');
        return;
    }

    const invoiceNo = document.getElementById('grnInwardInvoiceNo').value.trim();
    const receivedDate = document.getElementById('grnInwardReceivedDate').value;

    if (!invoiceNo) {
        showToast('Invoice No is required', 'error');
        return;
    }
    if (!receivedDate) {
        showToast('Received Date is required', 'error');
        return;
    }

    const rows = document.querySelectorAll('#grnInwardBody tr[data-idx]');
    const items = [];
    let hasError = false;

    // Cumulative received qty already recorded per line (from po.items[].receivedQty)
    // plus the qty being entered now must not exceed orderedQty * 1.05.
    rows.forEach(row => {
        const idx = parseInt(row.dataset.idx);
        const orderedQty = parseFloat(row.querySelector('.grn-ordered-qty').textContent) || 0;
        const receivedQty = parseFloat(row.querySelector('.grn-inward-qty').value) || 0;
        if (receivedQty < 0) {
            hasError = true;
            return;
        }
        const item = po.items[idx];
        if (!item) return;
        const previouslyReceived = parseFloat(item.receivedQty) || 0;
        const maxAllowed = orderedQty * 1.05;
        const wouldBeTotal = previouslyReceived + receivedQty;
        if (wouldBeTotal > maxAllowed + 0.001) {
            showToast('Row ' + (idx + 1) + ': ' + previouslyReceived.toFixed(2) +
                ' already received + ' + receivedQty.toFixed(2) +
                ' now exceeds 5% cap (' + maxAllowed.toFixed(2) + ')', 'error');
            hasError = true;
            return;
        }
        items.push({
            itemNo: item.itemNo || '',
            itemName: item.itemName || '',
            garmentSize: item.garmentSize || 'ALL',
            itemSize: item.itemSize || '',
            color: item.color || '',
            hsn: item.hsn || '',
            uom: item.uom || 'PCS',
            rate: parseFloat(item.rate) || 0,
            orderedQty: orderedQty,
            receivedQty: receivedQty,
            shortageQty: Math.max(0, orderedQty - receivedQty),
            requirementKey: item.requirementKey || ''
        });
    });

    if (hasError) return;

    // PO-level cumulative cap: sum of all lines already received + this batch
    // must not exceed sum-of-ordered * 1.05.
    let priorTotal = 0, orderedTotal = 0, incomingTotal = 0;
    items.forEach((it, i) => {
        const item = po.items[i] || {};
        priorTotal += parseFloat(item.receivedQty) || 0;
        orderedTotal += parseFloat(it.orderedQty) || 0;
        incomingTotal += parseFloat(it.receivedQty) || 0;
    });
    const poCap = orderedTotal * 1.05;
    if (priorTotal + incomingTotal > poCap + 0.001) {
        showToast('PO-level over-receipt: ' + priorTotal.toFixed(2) +
            ' already received + ' + incomingTotal.toFixed(2) +
            ' now exceeds PO cap (' + poCap.toFixed(2) + ')', 'error');
        return;
    }

    const btnId = isFinal ? 'grnInwardSaveBtn' : 'grnInwardReceiveBtn';
    const btn = document.getElementById(btnId);
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    try {
        const payload = {
            poToken: po.poToken || po.po_token,
            buyerOrderId: orderId,
            supplier: po.supplierAlias || po.supplier || '',
            invoiceNo: invoiceNo,
            receivedDate: receivedDate,
            items: items,
            isFinal: isFinal
        };

        const r = await API.call('/grn/receive', 'POST', payload);

        if (r.success) {
            showToast(r.message || (isFinal ? 'PO received & closed' : 'Partial inward saved'), 'success');
            // Q1a: both Receive and Receive & Close close the inward modal and
            // return the user to the GRN -> View POs list.
            closeGRNInwardModal();
            refreshGRNOrders();
            openGRNPOListModal(orderId);
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

function closeGRNInwardModal() {
    document.getElementById('grnInwardModal').classList.remove('active');
}

function openGRNModal(poToken) {
    const order = ERP_STATE.grnData.find(o => o.poToken === poToken);
    if (!order) {
        showToast('Order not found', 'error');
        return;
    }
    ERP_STATE.currentGRNData = order;
    document.getElementById('grnPOToken').textContent = poToken;
    document.getElementById('grnSupplier').innerHTML = `Supplier: <strong>${order.supplierAlias || order.supplier || ''}</strong>`;
    document.getElementById('grnInvoiceNo').value = '';
    renderGRNUnpacked(order);
    document.getElementById('grnModal').classList.add('active');
}

function renderGRNUnpacked(order) {
    const container = document.getElementById('grnFGGroupContainer');
    if (!order.groupedByFG || order.groupedByFG.length === 0) {
        container.innerHTML = '<div class="text-muted" style="text-align:center;padding:20px;">No FG groups found</div>';
        return;
    }
    let html = '';
    order.groupedByFG.forEach(fgGroup => {
        const fgKey = fgGroup.fgKey || 'Unknown FG';
        html += `<div class="grn-fg-group">
            <div class="fg-label">FG Key: <span class="fg-key-display">${fgKey}</span></div>
            <table style="width:100%;margin-top:4px;font-size:9px;">
                <thead><tr>
                    <th>Item No</th>
                    <th>Item Name</th>
                    <th>Size</th>
                    <th>Item Size</th>
                    <th>Ordered</th>
                    <th>Received</th>
                    <th>Balance</th>
                    <th>Rate</th>
                    <th>HSN</th>
                    <th style="min-width:60px;">Received Qty</th>
                </tr></thead>
                <tbody>`;
        fgGroup.items.forEach((item) => {
            const balance = item.balanceToReceive || 0;
            const isComplete = item.isComplete || false;
            const balanceClass = isComplete ? 'balance-complete' : 'balance-to-receive';
            const balanceText = isComplete ? '[OK] Complete' : balance.toFixed(2);
            html += `<tr data-po-token="${item.poToken || order.poToken}" data-fg-key="${fgKey}" data-item-no="${item.itemNo || ''}" data-garment-size="${item.garmentSize || 'ALL'}">
                <td>${item.itemNo || '—'}</td>
                <td>${item.itemName || '—'}</td>
                <td>${item.garmentSize || 'ALL'}</td>
                <td>${item.itemSize || ''}</td>
                <td>${(item.orderedQty || 0).toFixed(2)}</td>
                <td>${(item.receivedQty || 0).toFixed(2)}</td>
                <td class="${balanceClass}">${balanceText}</td>
                <td><input type="number" class="grn-rate" value="${item.rate || 0}" step="0.01" style="width:50px;"></td>
                <td><input type="text" class="grn-hsn" value="${item.hsn || ''}" style="width:50px;"></td>
                <td><input type="number" class="grn-qty" value="${balance > 0 ? balance.toFixed(2) : '0'}" step="0.01" style="width:60px;" ${isComplete ? 'disabled' : ''}></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    });
    container.innerHTML = html;
    updateGRNSummary();
}

function updateGRNSummary() {
    const qtyInputs = document.querySelectorAll('.grn-qty');
    let totalQty = 0;
    qtyInputs.forEach(input => {
        const val = parseFloat(input.value) || 0;
        totalQty += val;
    });
    const summary = document.getElementById('grnSummary');
    if (summary) summary.textContent = `[BOX] Total Receiving: ${totalQty.toFixed(2)} units`;
}

function closeGRNModal() {
    document.getElementById('grnModal').classList.remove('active');
    ERP_STATE.currentGRNData = null;
}

async function cancelGRNFromModal() {
    const poToken = document.getElementById('grnPOToken').textContent;
    const invoiceNo = document.getElementById('grnInvoiceNo').value.trim();
    if (!poToken) {
        showToast('No PO token found', 'error');
        return;
    }

    // Open the GRN cancellation modal instead of prompt() dialogs.
    openGRNCancelModal(poToken, invoiceNo);
}

function openGRNCancelModal(poToken, invoiceNo) {
    const existing = document.getElementById('grnCancelModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'grnCancelModal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:99999;';
    modal.innerHTML = `
        <div style="background:var(--bg-card);border-radius:12px;padding:24px 28px;max-width:520px;width:92%;border:1px solid var(--border-color);box-shadow:0 20px 60px rgba(0,0,0,0.35);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <h3 style="margin:0;color:var(--text-primary);">
                    <i class="fas fa-times-circle" style="color:#ea4335;"></i> Cancel GRN
                </h3>
                <button onclick="document.getElementById('grnCancelModal').remove()" style="background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-muted);">&times;</button>
            </div>
            <p class="text-muted" style="font-size:12px;margin:0 0 14px 0;">
                Cancels GRN for PO <strong>${poToken}</strong>${invoiceNo ? ' · Invoice ' + invoiceNo : ''}.
                This moves the buyer order back to RM Order and reverses received stock.
            </p>
            <div class="form-group" style="margin-bottom:10px;">
                <label style="font-size:13px;">Return Document No <span class="required">*</span></label>
                <input type="text" id="grnCancelReturnDoc" placeholder="e.g. RET-2026-001" style="width:100%;padding:8px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-input);color:var(--text-primary);">
            </div>
            <div class="form-group" style="margin-bottom:10px;">
                <label style="font-size:13px;">Reason for Cancellation <span class="required">*</span></label>
                <textarea id="grnCancelReason" rows="3" placeholder="Reason for cancelling this GRN..." style="width:100%;padding:8px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-input);color:var(--text-primary);font-family:inherit;"></textarea>
            </div>
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
                <button class="btn btn-outline" onclick="document.getElementById('grnCancelModal').remove()">Cancel</button>
                <button class="btn btn-danger" onclick="submitGRNCancel('${poToken}', '${invoiceNo || ''}')">
                    <i class="fas fa-times"></i> Confirm Cancellation
                </button>
            </div>
        </div>`;
    document.body.appendChild(modal);
}

async function submitGRNCancel(poToken, invoiceNo) {
    const returnDocNo = (document.getElementById('grnCancelReturnDoc').value || '').trim();
    const reason = (document.getElementById('grnCancelReason').value || '').trim();
    if (!returnDocNo) { showToast('Return Document No is required', 'error'); return; }
    if (!reason) { showToast('Reason for Cancellation is required', 'error'); return; }

    showToast('Cancelling GRN...', 'info');
    try {
        const r = await API.call('/grn/cancel', 'POST', {
            po_token: poToken,
            invoice_no: invoiceNo,
            return_doc_no: returnDocNo,
            cancel_reason: reason
        });
        if (r.success) {
            showToast(r.message, 'success');
            const m = document.getElementById('grnCancelModal');
            if (m) m.remove();
            closeGRNModal();
            refreshGRNOrders();
            refreshRMOrders();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function saveGRN() {
    const poToken = document.getElementById('grnPOToken').textContent;
    const invoiceNo = document.getElementById('grnInvoiceNo').value.trim();
    const rows = document.querySelectorAll('#grnFGGroupContainer tr[data-po-token]');
    const items = [];
    let hasError = false;

    rows.forEach(row => {
        const qtyInput = row.querySelector('.grn-qty');
        const rateInput = row.querySelector('.grn-rate');
        const hsnInput = row.querySelector('.grn-hsn');
        const qty = parseFloat(qtyInput?.value) || 0;
        const rate = parseFloat(rateInput?.value) || 0;

        if (qty < 0) {
            showToast('Received quantity cannot be negative', 'error');
            hasError = true;
            return;
        }
        if (qty === 0) return;

        const poToken = row.dataset.poToken || '';
        const fgKey = row.dataset.fgKey || '';
        const itemNo = row.dataset.itemNo || '';
        const garmentSize = row.dataset.garmentSize || 'ALL';
        const itemName = row.querySelector('td:nth-child(2)')?.textContent || '';
        const itemSize = row.querySelector('td:nth-child(4)')?.textContent || '';
        const color = row.querySelector('td:nth-child(3)')?.textContent || '';
        const orderedQty = parseFloat(row.querySelector('td:nth-child(5)')?.textContent) || 0;

        items.push({
            po_token: poToken,
            fg_key: fgKey,
            item_no: itemNo,
            garment_size: garmentSize,
            item_name: itemName,
            item_size: itemSize,
            color: color,
            ordered_qty: orderedQty,
            received_qty: qty,
            rate: rate,
            hsn: hsnInput?.value || '',
            uom: 'PCS',
            cgst: 0,
            igst: 0,
            requirement_key: ''
        });
    });

    if (hasError) return;
    if (items.length === 0) {
        showToast('No items to receive', 'error');
        return;
    }

    const grnData = { po_token: poToken, invoice_no: invoiceNo, items };
    showToast('Saving GRN...', 'info');
    try {
        const r = await API.saveGRN(grnData);
        if (r.success) {
            showToast(r.message, 'success');
            closeGRNModal();
            refreshGRNOrders();
            refreshRMOrders();
            refreshIssueRMOrders();
            if (r.hasShortfall) {
                showToast(`[WARN] Shortfall detected: ${r.shortfallCount} items`, 'warning');
            }
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function refreshShortfalls() {
    showToast('Loading shortfalls...', 'info');
    try {
        const data = await API.getPendingShortfalls();
        ERP_STATE.shortfallData = data || [];
        renderShortfalls(ERP_STATE.shortfallData);
        document.getElementById('shortfallModal').classList.add('active');
        showToast(ERP_STATE.shortfallData && ERP_STATE.shortfallData.length ? 'Shortfalls loaded' : 'No shortfalls found', ERP_STATE.shortfallData && ERP_STATE.shortfallData.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading shortfalls: ' + e.message, 'error');
    }
}

function renderShortfalls(shortfalls) {
    const container = document.getElementById('shortfallContainer');
    if (!shortfalls || shortfalls.length === 0) {
        container.innerHTML = '<div class="text-muted" style="text-align:center;padding:20px;">No pending shortfalls found.</div>';
        return;
    }
    let html = '';
    shortfalls.forEach(shortfall => {
        html += `<div class="shortfall-item">
            <div class="flex-between">
                <div><strong>FG: ${shortfall.fgKey || '—'}</strong> <span class="text-muted">| Item: ${shortfall.itemName || '—'}</span></div>
                <span class="shortfall-qty">Shortfall: ${(shortfall.shortfall || 0).toFixed(2)}</span>
            </div>
            <div style="font-size:10px;color:#856404;margin-top:2px;">Size: ${shortfall.garmentSize || 'ALL'} | Required: ${(shortfall.orderedQty || 0).toFixed(2)} | Received: ${(shortfall.receivedQty || 0).toFixed(2)}</div>
        </div>`;
    });
    container.innerHTML = html;
}

function closeShortfallModal() {
    document.getElementById('shortfallModal').classList.remove('active');
}

// ==============================================================
// SECTION 16: STAGE 6 - INTERNAL FG ORDER
// ==============================================================

async function refreshInternalFGOrders() {
    showToast('Loading Internal FG Orders...', 'info');
    try {
        const orders = await API.getInternalFGOrders();
        renderInternalFGOrders(orders);
        const countEl = document.getElementById('fgOrderCount');
        if (countEl) countEl.textContent = orders ? orders.length : 0;
        showToast(orders && orders.length ? 'FG orders loaded' : 'No FG orders found', orders && orders.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading FG orders: ' + e.message, 'error');
    }
}

function renderInternalFGOrders(orders) {
    const tb = document.getElementById('internalFGOrderBody');
    if (!tb) return;

    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">No orders in Internal FG Order stage.</td></tr>';
        return;
    }

    let html = '';
    orders.forEach(order => {
        const buyerOrderId = order.buyerOrderId || '—';
        const statusBadge = 'info';

        html += `<tr>
            <td><strong>${buyerOrderId}</strong></td>
            <td>${order.buyerName || '—'}</td>
            <td>${order.buyerOrderNo || '—'}</td>
            <td>${safeDate(order.orderDate)}</td>
            <td><span class="badge-status info">${order.totalFGs || 0}</span></td>
            <td><span class="badge-status ${statusBadge}">PENDING</span></td>
            <td>
                <button class="btn btn-primary btn-sm" onclick="openInternalFGModal('${buyerOrderId}')">
                    <i class="fas fa-industry"></i> Issue Factory Order
                </button>
                <button class="btn btn-danger btn-sm" onclick="cancelInternalFGBuyerOrder('${buyerOrderId}')">
                    <i class="fas fa-undo"></i> Cancel
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

async function openInternalFGModal(buyerOrderId) {
    if (!buyerOrderId) return;
    document.getElementById('ifgOrderId').textContent = buyerOrderId;
    const tb = document.getElementById('internalFGModalBody');
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">Loading FGs...</td></tr>';
    document.getElementById('ifgModalSummary').textContent = '';
    document.getElementById('internalFGModal').classList.add('active');

    try {
        const orders = await API.getInternalFGOrders();
        const order = (orders || []).find(o => o.buyerOrderId === buyerOrderId);
        if (!order) {
            tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#ea4335;padding:16px;">Order not found in this stage.</td></tr>';
            return;
        }

        document.getElementById('ifgBuyerName').textContent = order.buyerName || '—';
        document.getElementById('ifgBuyerOrderNo').textContent = order.buyerOrderNo || '—';
        document.getElementById('ifgOrderDate').textContent = safeDate(order.orderDate);

        window._ifgCurrentOrder = order;

        if (!order.fgs || order.fgs.length === 0) {
            tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No FGs in this order.</td></tr>';
            return;
        }

        let html = '';
        order.fgs.forEach((fg, idx) => {
            const sizes = fg.sizes || [];
            const sizeQtys = fg.sizeQtys || {};
            let sizeText = '';
            sizes.forEach(s => {
                const q = sizeQtys[String(s)] || 0;
                if (q > 0) sizeText += `${s}:${q} `;
            });
            if (!sizeText) sizeText = '—';

            html += `<tr data-idx="${idx}" data-fg-key="${fg.fgKey}">
                <td style="text-align:center;">${idx + 1}</td>
                <td><strong>${fg.design || '—'}</strong></td>
                <td>${fg.color || '—'}</td>
                <td style="font-size:11px;max-width:240px;">${sizeText}</td>
                <td style="text-align:right;" class="ifg-base-qty">${(fg.totalQty || 0).toFixed(2)}</td>
                <td>
                    <input type="number" class="ifg-extra-pct" min="0" max="7" step="0.5" value="0"
                        style="width:80px;text-align:right;"
                        oninput="recalcIFGRow(this)">
                </td>
                <td style="text-align:right;" class="ifg-extra-qty">0.00</td>
                <td style="text-align:right;" class="ifg-factory-qty">${(fg.totalQty || 0).toFixed(2)}</td>
            </tr>`;
        });
        tb.innerHTML = html;
        updateIFGSummary();
    } catch (e) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

function recalcIFGRow(input) {
    let pct = parseFloat(input.value) || 0;
    if (pct < 0) pct = 0;
    if (pct > 7) {
        pct = 7;
        input.value = 7;
        showToast('Extra % capped at 7%', 'warning');
    }
    const row = input.closest('tr');
    const baseQty = parseFloat(row.querySelector('.ifg-base-qty').textContent) || 0;
    const extraQty = baseQty * (pct / 100);
    const factoryQty = baseQty + extraQty;
    row.querySelector('.ifg-extra-qty').textContent = extraQty.toFixed(2);
    row.querySelector('.ifg-factory-qty').textContent = factoryQty.toFixed(2);
    updateIFGSummary();
}

function updateIFGSummary() {
    const rows = document.querySelectorAll('#internalFGModalBody tr[data-idx]');
    let totalBase = 0, totalFactory = 0;
    rows.forEach(r => {
        totalBase += parseFloat(r.querySelector('.ifg-base-qty').textContent) || 0;
        totalFactory += parseFloat(r.querySelector('.ifg-factory-qty').textContent) || 0;
    });
    const summary = document.getElementById('ifgModalSummary');
    if (summary) {
        summary.textContent = `FGs: ${rows.length} | Base: ${totalBase.toFixed(2)} | Factory: ${totalFactory.toFixed(2)} (Extra: ${(totalFactory - totalBase).toFixed(2)})`;
    }
}

async function submitFactoryOrder() {
    const order = window._ifgCurrentOrder;
    if (!order) {
        showToast('No order loaded', 'error');
        return;
    }

    const rows = document.querySelectorAll('#internalFGModalBody tr[data-idx]');
    const fg_data = [];
    let hasError = false;

    rows.forEach(row => {
        const fgKey = row.dataset.fgKey;
        const pct = parseFloat(row.querySelector('.ifg-extra-pct').value) || 0;
        if (pct < 0 || pct > 7) {
            hasError = true;
            return;
        }
        fg_data.push({
            fgKey: fgKey,
            extraPercentage: pct
        });
    });

    if (hasError) {
        showToast('Extra % must be between 0 and 7', 'error');
        return;
    }
    if (fg_data.length === 0) {
        showToast('No FGs to issue', 'error');
        return;
    }

    if (!confirm('Issue factory orders with these wastage percentages? This will move the order to Issue RM stage.')) return;

    const btn = document.getElementById('ifgSubmitBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Issuing...';

    try {
        const r = await API.call('/internal-fg/issue-factory-order', 'POST', {
            buyer_order_id: order.buyerOrderId,
            fg_data: fg_data
        });

        if (r.success) {
            showToast(r.message, 'success');
            closeModal('internalFGModal');
            refreshInternalFGOrders();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check"></i> Issue Factory Order';
    }
}

async function processInternalFG(internalOrderId) {
    if (!confirm(`Process Internal FG Order ${internalOrderId}?`)) return;
    showToast('Processing...', 'info');
    try {
        const r = await API.call('/internal-fg/process', 'POST', { internal_order_id: internalOrderId });
        if (r.success) {
            showToast(r.message, 'success');
            refreshInternalFGOrders();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function cancelInternalFGBuyerOrder(buyerOrderId) {
    if (!buyerOrderId) return;
    const existing = document.getElementById('ifgCancelModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'ifgCancelModal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:99999;';
    modal.innerHTML = `
        <div style="background:var(--bg-card);border-radius:12px;padding:24px 28px;max-width:520px;width:92%;border:1px solid var(--border-color);box-shadow:0 20px 60px rgba(0,0,0,0.35);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <h3 style="margin:0;color:var(--text-primary);">
                    <i class="fas fa-times-circle" style="color:#ea4335;"></i> Cancel Internal FG Order
                </h3>
                <button onclick="document.getElementById('ifgCancelModal').remove()" style="background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-muted);">&times;</button>
            </div>
            <p class="text-muted" style="font-size:12px;margin:0 0 14px 0;">
                Cancels the factory order(s) for <strong>${buyerOrderId}</strong>.
                This reverses the GRN intake (stock out), returns the PO to <strong>NR</strong>, and moves the buyer order back to <strong>GRN</strong>.
            </p>
            <div class="form-group" style="margin-bottom:10px;">
                <label style="font-size:13px;">Return Document No <span class="required">*</span></label>
                <input type="text" id="ifgCancelReturnDoc" placeholder="e.g. RET-2026-001" style="width:100%;padding:8px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-input);color:var(--text-primary);">
            </div>
            <div class="form-group" style="margin-bottom:10px;">
                <label style="font-size:13px;">Reason for Cancellation <span class="required">*</span></label>
                <textarea id="ifgCancelReason" rows="3" placeholder="Reason for cancelling this Internal FG Order..." style="width:100%;padding:8px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-input);color:var(--text-primary);font-family:inherit;"></textarea>
            </div>
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
                <button class="btn btn-outline" onclick="document.getElementById('ifgCancelModal').remove()">Cancel</button>
                <button class="btn btn-danger" onclick="submitIFGCancel('${buyerOrderId}')">
                    <i class="fas fa-times"></i> Confirm Cancellation
                </button>
            </div>
        </div>`;
    document.body.appendChild(modal);
}

async function submitIFGCancel(buyerOrderId) {
    const returnDocNo = (document.getElementById('ifgCancelReturnDoc').value || '').trim();
    const reason = (document.getElementById('ifgCancelReason').value || '').trim();
    if (!returnDocNo) { showToast('Return Document No is required', 'error'); return; }
    if (!reason) { showToast('Reason for Cancellation is required', 'error'); return; }

    showToast('Cancelling Internal FG Order...', 'info');
    try {
        const r = await API.call('/internal-fg/cancel-buyer-order', 'POST', {
            buyer_order_id: buyerOrderId,
            return_doc_no: returnDocNo,
            cancel_reason: reason
        });
        if (r.success) {
            showToast(r.message || 'Internal FG Order cancelled', 'success');
            const m = document.getElementById('ifgCancelModal');
            if (m) m.remove();
            refreshInternalFGOrders();
            refreshGRNOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function cancelInternalFG(internalOrderId) {
    if (!confirm(`Cancel Internal FG Order ${internalOrderId}?`)) return;
    showToast('Cancelling...', 'info');
    try {
        const r = await API.call('/internal-fg/cancel', 'POST', { internal_order_id: internalOrderId });
        if (r.success) {
            showToast(r.message, 'success');
            refreshInternalFGOrders();
            refreshGRNOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 17: STAGE 7 - ISSUE RM
// ==============================================================

async function refreshIssueRMOrders() {
    showToast('Loading pending issues...', 'info');
    try {
        const orders = await API.getIssueRMOrders();
        ERP_STATE.issueRMData = orders || [];
        renderIssueRMOrders(ERP_STATE.issueRMData);
        const countEl = document.getElementById('issueCount');
        if (countEl) countEl.textContent = orders ? orders.length : 0;
        showToast(ERP_STATE.issueRMData && ERP_STATE.issueRMData.length ? 'Pending issues loaded' : 'No pending issues', ERP_STATE.issueRMData && ERP_STATE.issueRMData.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading issues: ' + e.message, 'error');
    }
}

function renderIssueRMOrders(orders) {
    const tb = document.getElementById('issueRMOrderBody');
    if (!tb) return;
    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#62748e;padding:16px;">No orders in Issue RM stage.</td></tr>';
        return;
    }
    let html = '';
    orders.forEach(o => {
        const statusMap = { 'COMPLETED': 'success', 'PARTIAL': 'partial', 'PENDING': 'pending-issue' };
        const statusBadge = statusMap[o.status] || 'pending-issue';
        const available = o.available || 0;
        const canIssue = available > 0 && o.status !== 'COMPLETED';
        html += `<tr>
            <td><strong>${o.buyerOrderNo || '—'}</strong></td>
            <td>${o.buyerName || '—'}</td>
            <td>${(o.required || 0).toFixed(2)}</td>
            <td>${(o.grnReceived || 0).toFixed(2)}</td>
            <td>${(o.issued || 0).toFixed(2)}</td>
            <td>${(available).toFixed(2)}</td>
            <td><span class="badge-status ${statusBadge}">${o.status}</span></td>
            <td>
                <button class="btn btn-success btn-sm" onclick="openIssueRMBuyerModal('${o.buyerOrderId}')" ${!canIssue ? 'disabled' : ''}>
                    <i class="fas fa-arrow-right-from-bracket"></i> Issue
                </button>
                <button class="btn btn-danger btn-sm" onclick="cancelIssueRMOrder('${o.buyerOrderId}')">
                    <i class="fas fa-undo"></i> Cancel
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

async function cancelIssueRMOrder(buyerOrderId) {
    if (!buyerOrderId) return;
    if (!confirm('Cancel Issue RM for this buyer order?\nThis will move the order back to Internal FG Order stage.')) return;
    showToast('Cancelling...', 'info');
    try {
        const r = await API.call('/issue-rm/cancel', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || 'Issue RM cancelled', 'success');
            refreshIssueRMOrders();
            refreshInternalFGOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function openIssueRMBuyerModal(buyerOrderId) {
    if (!buyerOrderId) return;
    document.getElementById('issueBuyerOrderNo').textContent = buyerOrderId;
    document.getElementById('issueFGGrids').innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fas fa-spinner fa-spin" style="font-size:24px;"></i></div>';
    document.getElementById('issueRMBuyerModal').classList.add('active');

    try {
        const r = await API.call('/issue-rm/buyer-order/' + encodeURIComponent(buyerOrderId));
        if (!r.success) {
            document.getElementById('issueFGGrids').innerHTML = '<div style="text-align:center;padding:30px;color:#ea4335;">Error: ' + (r.message || 'Unknown') + '</div>';
            return;
        }
        document.getElementById('issueBuyerMeta').innerHTML = 'Buyer: <strong>' + (r.buyerName || '—') + '</strong> | Order No: <strong>' + (r.buyerOrderNo || '—') + '</strong> | FGs: <strong>' + r.totalFGs + '</strong>';
        window._issueBuyerOrderId = buyerOrderId;
        renderIssueRMGrids(r.fgs || []);
    } catch (e) {
        document.getElementById('issueFGGrids').innerHTML = '<div style="text-align:center;padding:30px;color:#ea4335;">Error: ' + e.message + '</div>';
    }
}

function renderIssueRMGrids(fgs) {
    const container = document.getElementById('issueFGGrids');
    if (!fgs || fgs.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">No FGs found.</div>';
        return;
    }
    let html = '';
    fgs.forEach((fg, fgIdx) => {
        html += `<div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;margin-bottom:18px;overflow:hidden;">`;
        html += `<div style="background:var(--table-header);padding:10px 16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--border-color);">`;
        html += `<span><strong>FG ${fgIdx + 1}:</strong> ${fg.design || '—'} | Color: <strong>${fg.color || '—'}</strong></span>`;
        html += `<span style="font-size:12px;color:var(--text-muted);">Order Qty: <strong>${(fg.orderQty || 0).toFixed(2)}</strong> (Base: ${(fg.baseQty || 0).toFixed(2)} + Extra: ${(fg.extraPercent || 0).toFixed(2)}%)</span>`;
        html += `</div>`;
        html += `<div style="padding:12px;overflow-x:auto;">`;
        html += `<table style="width:100%;font-size:12px;border-collapse:collapse;">`;
        html += `<thead><tr style="background:var(--bg-input);">`;
        html += `<th style="padding:6px 8px;text-align:left;">Item No</th>`;
        html += `<th style="padding:6px 8px;text-align:left;">Item Name</th>`;
        html += `<th style="padding:6px 8px;text-align:left;">Garment Size</th>`;
        html += `<th style="padding:6px 8px;text-align:left;">Color</th>`;
        html += `<th style="padding:6px 8px;text-align:right;">Order Qty</th>`;
        html += `<th style="padding:6px 8px;text-align:right;">Consumption</th>`;
        html += `<th style="padding:6px 8px;text-align:right;">Required</th>`;
        html += `<th style="padding:6px 8px;text-align:right;">Available</th>`;
        html += `<th style="padding:6px 8px;text-align:center;min-width:100px;">Issue Qty</th>`;
        html += `</tr></thead><tbody>`;

        fg.items.forEach(item => {
            const available = item.availableQty || 0;
            const maxIssuable = Math.min(available, item.requiredQty * 1.05);
            const defaultQty = Math.max(0, Math.min(available, item.requiredQty || 0));
            const _rqKey = (item.requirementKey || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
            html += `<tr data-requirement-key="${_rqKey}" data-max="${maxIssuable}">`;
            html += `<td style="padding:4px 6px;">${item.itemNo || '—'}</td>`;
            html += `<td style="padding:4px 6px;">${item.itemName || '—'}</td>`;
            html += `<td style="padding:4px 6px;">${item.garmentSize || 'ALL'}</td>`;
            html += `<td style="padding:4px 6px;">${item.color || ''}</td>`;
            html += `<td style="padding:4px 6px;text-align:right;">${(item.orderQty || 0).toFixed(2)}</td>`;
            html += `<td style="padding:4px 6px;text-align:right;">${(item.consumption || 0).toFixed(4)}</td>`;
            html += `<td style="padding:4px 6px;text-align:right;">${(item.requiredQty || 0).toFixed(2)}</td>`;
            html += `<td style="padding:4px 6px;text-align:right;">${available.toFixed(2)}</td>`;
            html += `<td style="padding:4px 6px;text-align:center;"><input type="number" class="issue-rm-qty" min="0" step="0.01" value="${defaultQty.toFixed(2)}" style="width:90px;text-align:right;" oninput="validateIssueRMQty(this, ${available}, ${maxIssuable})"></td>`;
            html += `</tr>`;
        });
        html += `</tbody></table></div></div>`;
    });
    container.innerHTML = html;
}

function validateIssueRMQty(input, available, maxIssuable) {
    let v = parseFloat(input.value) || 0;
    if (v < 0) { v = 0; }
    if (v > available + 0.001) {
        showToast('Issue qty exceeds available stock (' + available.toFixed(2) + ')', 'error');
        input.value = available.toFixed(2);
        return;
    }
    if (v > maxIssuable + 0.001) {
        showToast('Issue qty exceeds 5% buffer limit (' + maxIssuable.toFixed(2) + ')', 'error');
        input.value = maxIssuable.toFixed(2);
        return;
    }
    input.value = v.toFixed(2);
}

function closeIssueRMBuyerModal() {
    document.getElementById('issueRMBuyerModal').classList.remove('active');
}

async function saveAllIssueRM() {
    const buyerOrderId = window._issueBuyerOrderId;
    if (!buyerOrderId) { showToast('No order loaded', 'error'); return; }

    const rows = document.querySelectorAll('#issueFGGrids tr[data-requirement-key]');
    const items = [];
    rows.forEach(row => {
        const reqKey = row.dataset.requirementKey;
        const qtyInput = row.querySelector('.issue-rm-qty');
        const qty = parseFloat(qtyInput.value) || 0;
        if (qty <= 0) return;
        items.push({
            requirement_key: reqKey,
            issuing_qty: qty
        });
    });

    if (items.length === 0) {
        showToast('No quantities to issue', 'error');
        return;
    }

    if (!confirm('Issue ' + items.length + ' item(s)? Buyer order will move to FG Inspection.')) return;

    const btn = document.getElementById('issueRMSaveBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Issuing...';

    try {
        const r = await API.call('/issue-rm/save-bulk', 'POST', {
            buyer_order_id: buyerOrderId,
            items: items
        });
        if (r.success) {
            showToast(r.message || 'Issued successfully', 'success');
            closeIssueRMBuyerModal();
            refreshIssueRMOrders();
            refreshFGInspections();
            refreshRMInventory();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check"></i> Issue All &amp; Move to FG Inspection';
    }
}

async function openIssueRMModal(fgKey) {
    document.getElementById('issueModalFGKey').innerHTML = `FG Key: <strong>${fgKey}</strong>`;
    document.getElementById('issueModalStatus').innerHTML = 'Status: <strong>Loading...</strong>';
    document.getElementById('issueSummary').textContent = 'Loading requirements...';
    try {
        const items = await API.getIssuableItems(fgKey);
        renderIssueRMItems(items, fgKey);
        const totalAvailable = items.reduce((sum, i) => sum + i.availableToIssue, 0);
        document.getElementById('issueSummary').textContent = `${items.length} items · Available: ${totalAvailable.toFixed(2)} units`;
        document.getElementById('issueModalStatus').innerHTML = `Status: <strong>${totalAvailable > 0 ? 'Ready' : 'Complete'}</strong>`;
        document.getElementById('issueRMModal').classList.add('active');
    } catch (e) {
        showToast('Error loading items: ' + e.message, 'error');
    }
}

function renderIssueRMItems(items) {
    const tb = document.getElementById('issueRMItemsBody');
    if (!items || items.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#62748e;">No items</td></tr>';
        return;
    }
    let html = '';
    items.forEach((item, idx) => {
        const available = item.availableToIssue || 0;
        const maxIssuable = item.maxIssuable || item.requiredQty * 1.05;
        const defaultQty = Math.min(available, maxIssuable);
        html += `<tr data-requirement-key="${item.requirementKey || ''}">
            <td>${item.itemName || '—'}</td>
            <td>${item.garmentSize || 'ALL'}</td>
            <td>${item.itemSize || ''}</td>
            <td>${(item.requiredQty || 0).toFixed(2)}</td>
            <td>${(item.grnQty || 0).toFixed(2)}</td>
            <td>${(item.issuedQty || 0).toFixed(2)}</td>
            <td><span class="${available > maxIssuable ? 'issue-buffer-warning' : 'issue-buffer-ok'}">${(available).toFixed(2)}</span></td>
            <td><input type="number" class="issue-qty" data-idx="${idx}" value="${Math.min(defaultQty, maxIssuable).toFixed(2)}" step="0.01" style="width:70px;" onchange="validateIssueQty(${idx}, this.value)"></td>
        </tr>`;
    });
    tb.innerHTML = html;
}

function validateIssueQty(idx, value) {
    const row = document.querySelector(`#issueRMItemsBody tr:nth-child(${idx + 1})`);
    if (!row) return;
    const availableCell = row.querySelector('td:nth-child(7)');
    const available = parseFloat(availableCell?.textContent || 0);
    const qty = parseFloat(value) || 0;
    if (qty > available) {
        showToast(`[ERR] Issuance exceeds available limit. Available: ${available.toFixed(2)}`, 'error');
        row.querySelector('.issue-qty').value = available.toFixed(2);
    }
}

function closeIssueRMModal() {
    document.getElementById('issueRMModal').classList.remove('active');
}

async function saveIssueRM() {
    const fgKey = document.getElementById('issueModalFGKey').textContent.replace('FG Key: ', '').trim();
    const rows = document.querySelectorAll('#issueRMItemsBody tr');
    const items = [];
    let hasError = false;
    rows.forEach((row, idx) => {
        const qtyInput = row.querySelector('.issue-qty');
        const qty = parseFloat(qtyInput?.value) || 0;
        if (qty < 0) {
            showToast(`Row ${idx + 1}: Quantity cannot be negative`, 'error');
            hasError = true;
            return;
        }
        if (qty === 0) return;

        const availableCell = row.querySelector('td:nth-child(7)');
        const available = parseFloat(availableCell?.textContent || 0);
        if (qty > available) {
            showToast(`[ERR] Row ${idx + 1}: Issuance exceeds available limit. Available: ${available.toFixed(2)}`, 'error');
            hasError = true;
            return;
        }
        const garmentSize = row.querySelector('td:nth-child(2)')?.textContent || 'ALL';
        const itemSize = row.querySelector('td:nth-child(3)')?.textContent || '';
        const requirementKey = row.dataset.requirementKey || '';
        const itemName = row.querySelector('td:nth-child(1)')?.textContent || '';
        const requiredQty = parseFloat(row.querySelector('td:nth-child(4)')?.textContent) || 0;

        items.push({
            item_no: '',
            item_name: itemName,
            garment_size: garmentSize,
            item_size: itemSize,
            color: '',
            required_qty: requiredQty,
            issuing_qty: qty,
            uom: 'PCS',
            requirement_key: requirementKey
        });
    });
    if (hasError) return;
    if (items.length === 0) {
        showToast('Please issue at least one item', 'error');
        return;
    }
    const issueData = { fg_key: fgKey, items };
    showToast('Issuing items...', 'info');
    try {
        const r = await API.saveIssueRM(issueData);
        if (r.success) {
            showToast(r.message, 'success');
            closeIssueRMModal();
            refreshIssueRMOrders();
            if (r.allComplete) {
                showToast('[DONE] All requirements fulfilled! Order closed.', 'success');
            }
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 18: STAGE 8 - FG INSPECTION
// ==============================================================

async function refreshFGInspections() {
    showToast('Loading FG inspections...', 'info');
    try {
        const data = await API.getFGInspections();
        renderFGInspections(data);
        const countEl = document.getElementById('fgInspectionCount');
        if (countEl) countEl.textContent = data ? data.length : 0;
        showToast(data && data.length ? 'FG inspections loaded' : 'No FG inspections found', data && data.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading FG inspections: ' + e.message, 'error');
    }
}

function renderFGInspections(orders) {
    const tb = document.getElementById('fgInspectionBody');
    if (!tb) return;

    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No orders in FG Inspection stage.</td></tr>';
        return;
    }

    let html = '';
    orders.forEach(o => {
        const failCount = o.failCount || 0;
        const failBadge = failCount > 0
            ? `<span class="badge-status danger">${failCount}</span>`
            : `<span class="badge-status info">0</span>`;
        html += `<tr>
            <td><strong>${o.buyerOrderId || '—'}</strong></td>
            <td>${o.buyerName || '—'}</td>
            <td>${o.buyerOrderNo || '—'}</td>
            <td>${safeDate(o.orderDate)}</td>
            <td>${(o.orderQty || o.producedQty || 0).toFixed(2)}</td>
            <td>${failBadge}</td>
            <td><span class="badge-status warning">${o.status || 'PENDING'}</span></td>
            <td>
                <button class="btn btn-success btn-xs" onclick="inspectBuyerOrder('${o.buyerOrderId}')">
                    <i class="fas fa-clipboard-check"></i> Inspect
                </button>
                <button class="btn btn-danger btn-xs" onclick="cancelFGInspection('${o.buyerOrderId}')">
                    <i class="fas fa-undo"></i> Cancel
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

async function inspectBuyerOrder(buyerOrderId) {
    if (!buyerOrderId) return;
    document.getElementById('fgInspOrderId').textContent = buyerOrderId;
    document.getElementById('fgInspMeta').innerHTML = 'Loading...';
    document.getElementById('fgInspDetailBody').innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);padding:16px;">Loading...</td></tr>';
    document.getElementById('fgInspectionDetailModal').classList.add('active');

    try {
        const r = await API.call('/fg-inspection/detail/' + encodeURIComponent(buyerOrderId));
        if (!r.success) {
            document.getElementById('fgInspDetailBody').innerHTML = '<tr><td colspan="10" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + (r.message || 'Unknown') + '</td></tr>';
            return;
        }
        document.getElementById('fgInspMeta').innerHTML = 'Buyer: <strong>' + (r.buyerName || '—') + '</strong> | Order No: <strong>' + (r.buyerOrderNo || '—') + '</strong> | Fail Count: <strong style="color:#ea4335;">' + (r.failCount || 0) + '</strong> | FGs: <strong>' + r.totalFGs + '</strong>';
        window._fgInspBuyerOrderId = buyerOrderId;
        window._fgInspData = r.fgs || [];
        renderFGInspectionRows(r.fgs || []);
    } catch (e) {
        document.getElementById('fgInspDetailBody').innerHTML = '<tr><td colspan="10" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

function renderFGInspectionRows(fgs) {
    const tb = document.getElementById('fgInspDetailBody');
    if (!fgs || fgs.length === 0) {
        tb.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);padding:16px;">No FGs found.</td></tr>';
        return;
    }
    let html = '';
    fgs.forEach((fg, idx) => {
        const lastStatus = fg.lastStatus === 'PASSED'
            ? '<span class="badge-status success">PASSED</span>'
            : (fg.lastStatus === 'FAILED' ? '<span class="badge-status danger">FAILED</span>' : '<span class="badge-status info">—</span>');
        html += `<tr data-fg-key="${fg.fgKey}" data-order-qty="${fg.orderQty}">
            <td style="text-align:center;">${idx + 1}</td>
            <td><strong>${fg.design || '—'}</strong></td>
            <td>${fg.color || '—'}</td>
            <td style="text-align:right;" class="fg-order-qty">${(fg.orderQty || 0).toFixed(2)}</td>
            <td><input type="number" class="fg-presented-qty" min="0" step="0.01" value="${(fg.presentedQty || fg.orderQty || 0).toFixed(2)}" style="width:100px;text-align:right;" oninput="validatePresentedQty(this)"></td>
            <td><input type="number" class="fg-inspected-qty" min="0" step="0.01" value="${(fg.inspectedQty || fg.presentedQty || fg.orderQty || 0).toFixed(2)}" style="width:100px;text-align:right;" oninput="validateInspectedQty(this)"></td>
            <td><input type="number" class="fg-minor" min="0" step="1" value="${fg.minor || 0}" style="width:70px;text-align:right;"></td>
            <td><input type="number" class="fg-major" min="0" step="1" value="${fg.major || 0}" style="width:70px;text-align:right;"></td>
            <td><input type="number" class="fg-critical" min="0" step="1" value="${fg.critical || 0}" style="width:70px;text-align:right;"></td>
            <td style="text-align:center;">${lastStatus}</td>
        </tr>`;
    });
    tb.innerHTML = html;
}

function validatePresentedQty(input) {
    const row = input.closest('tr');
    const orderQty = parseFloat(row.dataset.orderQty) || 0;
    let v = parseFloat(input.value) || 0;
    const min = orderQty * 0.95;
    const max = orderQty * 1.05;
    if (v < min - 0.01) {
        showToast('Presented Qty must be at least ' + min.toFixed(2) + ' (±5% of Order Qty)', 'error');
        input.value = min.toFixed(2);
        return;
    }
    if (v > max + 0.01) {
        showToast('Presented Qty must be at most ' + max.toFixed(2) + ' (±5% of Order Qty)', 'error');
        input.value = max.toFixed(2);
        return;
    }
}

function validateInspectedQty(input) {
    const row = input.closest('tr');
    const presented = parseFloat(row.querySelector('.fg-presented-qty').value) || 0;
    let v = parseFloat(input.value) || 0;
    if (v > presented + 0.01) {
        showToast('Inspected Qty cannot exceed Presented Qty (' + presented.toFixed(2) + ')', 'error');
        input.value = presented.toFixed(2);
    }
}

function closeFGInspectionModal() {
    document.getElementById('fgInspectionDetailModal').classList.remove('active');
}

async function submitFGInspection(decision) {
    const buyerOrderId = window._fgInspBuyerOrderId;
    if (!buyerOrderId) { showToast('No order loaded', 'error'); return; }

    const rows = document.querySelectorAll('#fgInspDetailBody tr[data-fg-key]');
    const payload = [];
    let hasError = false;
    rows.forEach(row => {
        const fgKey = row.dataset.fgKey;
        const orderQty = parseFloat(row.dataset.orderQty) || 0;
        const presented = parseFloat(row.querySelector('.fg-presented-qty').value) || 0;
        const inspected = parseFloat(row.querySelector('.fg-inspected-qty').value) || 0;
        const minor = parseInt(row.querySelector('.fg-minor').value) || 0;
        const major = parseInt(row.querySelector('.fg-major').value) || 0;
        const critical = parseInt(row.querySelector('.fg-critical').value) || 0;

        if (orderQty > 0) {
            const min = orderQty * 0.95, max = orderQty * 1.05;
            if (presented < min - 0.01 || presented > max + 0.01) {
                showToast(fgKey + ': Presented Qty outside ±5% of Order Qty', 'error');
                hasError = true;
                return;
            }
        }
        if (inspected > presented + 0.01) {
            showToast(fgKey + ': Inspected Qty exceeds Presented Qty', 'error');
            hasError = true;
            return;
        }

        payload.push({ fgKey, orderQty, presentedQty: presented, inspectedQty: inspected, minor, major, critical });
    });

    if (hasError) return;
    if (payload.length === 0) { showToast('No rows to submit', 'error'); return; }

    const confirmMsg = decision === 'PASS'
        ? 'PASS inspection? Buyer order will move to FG Inventory.'
        : 'FAIL inspection? Buyer order stays in FG Inspection. Fail counter will increment.';
    if (!confirm(confirmMsg)) return;

    const btnId = decision === 'PASS' ? 'fgInspPassBtn' : 'fgInspFailBtn';
    const btn = document.getElementById(btnId);
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting...';

    try {
        const r = await API.call('/fg-inspection/submit', 'POST', {
            buyer_order_id: buyerOrderId,
            decision: decision,
            inspector: 'admin',
            rows: payload
        });
        if (r.success) {
            showToast(r.message, 'success');
            if (decision === 'PASS') {
                closeFGInspectionModal();
            } else {
                // Reload the modal to refresh fail count and last status
                inspectBuyerOrder(buyerOrderId);
            }
            refreshFGInspections();
            if (decision === 'PASS') refreshFGInventory();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function cancelFGInspection(buyerOrderId) {
    if (!buyerOrderId) return;
    if (!confirm('Cancel FG Inspection for this buyer order?\nThis will move the order back to Issue RM stage.')) return;
    showToast('Cancelling...', 'info');
    try {
        const r = await API.call('/fg-inspection/cancel', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || 'Cancelled', 'success');
            refreshFGInspections();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function passFGInspection(inspectionId) {
    if (!confirm(`Pass FG Inspection ${inspectionId}?`)) return;
    showToast('Processing...', 'info');
    try {
        const r = await API.call('/fg-inspection/pass', 'POST', { inspection_id: inspectionId });
        if (r.success) {
            showToast(r.message, 'success');
            refreshFGInspections();
            refreshFGInventory();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function failFGInspection(inspectionId) {
    if (!confirm(`Fail FG Inspection ${inspectionId}?`)) return;
    showToast('Processing...', 'info');
    try {
        const r = await API.call('/fg-inspection/fail', 'POST', { inspection_id: inspectionId });
        if (r.success) {
            showToast(r.message, 'success');
            refreshFGInspections();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 19: STAGE 9 - FG INVENTORY
// ==============================================================

async function refreshFGInventory() {
    showToast('Loading FG inventory...', 'info');
    try {
        const data = await API.call('/fg-inventory/orders');
        renderFGInventory(data);
        const countEl = document.getElementById('fgInvCount');
        if (countEl) countEl.textContent = data ? data.length : 0;
        showToast(data && data.length ? 'FG inventory loaded' : 'No FG inventory found', data && data.length ? 'success' : 'info');
    } catch (e) {
        showToast('Error loading FG inventory: ' + e.message, 'error');
    }
}

function renderFGInventory(orders) {
    const tb = document.getElementById('fgInventoryBody');
    if (!tb) return;

    // Update global counters
    let totalFGs = 0;
    let totalQty = 0;
    let balancePcs = 0;
    (orders || []).forEach(o => {
        totalFGs += (o.fgCount || 0);
        totalQty += (o.totalQty || 0);
        balancePcs += (o.balancePcs || 0);
    });
    const totalFGsEl = document.getElementById('fgInventoryTotalFGs');
    const totalQtyEl = document.getElementById('fgInventoryTotalQty');
    const balancePcsEl = document.getElementById('fgInventoryBalancePcs');
    if (totalFGsEl) totalFGsEl.textContent = totalFGs;
    if (totalQtyEl) totalQtyEl.textContent = Math.ceil(totalQty);
    if (balancePcsEl) balancePcsEl.textContent = Math.ceil(balancePcs);

    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No FGs in inventory.</td></tr>';
        return;
    }

    let html = '';
    orders.forEach(o => {
        const breakdownText = (o.fgBreakdown || [])
            .map(fg => `${fg.design} | ${fg.color}: ${Math.ceil(fg.qty || 0)}`)
            .join('&#10;');
        const totalRounded = Math.ceil(o.totalQty || 0);
        const totalCell = breakdownText
            ? `<strong title="${breakdownText}" style="cursor:help;border-bottom:1px dotted #888;">${totalRounded}</strong>`
            : `<strong>${totalRounded}</strong>`;
        
        const balanceBreakdownText = (o.balanceBreakdown || [])
            .map(fg => `${fg.design} | ${fg.color}: ${Math.ceil(fg.qty || 0)}`)
            .join('&#10;');
        const balanceRounded = Math.ceil(o.balancePcs || 0);
        const balanceCell = balanceBreakdownText
            ? `<strong title="${balanceBreakdownText}" style="cursor:help;border-bottom:1px dotted #888;color:#34a853;">${balanceRounded}</strong>`
            : `<strong style="color:#34a853;">${balanceRounded}</strong>`;
        
        html += `<tr>
            <td><strong>${o.buyerOrderId || '—'}</strong></td>
            <td>${o.buyerName || '—'}</td>
            <td>${o.buyerOrderNo || '—'}</td>
            <td>${safeDate(o.orderDate)}</td>
            <td><span class="badge-status info">${o.fgCount || 0}</span></td>
            <td>${totalCell}</td>
            <td>${balanceCell}</td>
            <td>
                <button class="btn btn-primary btn-sm" onclick="openDispatchModal('${o.buyerOrderId}')">
                    <i class="fas fa-truck"></i> Dispatch
                </button>
                <button class="btn btn-warning btn-sm" onclick="sendBackToInspection('${o.buyerOrderId}')">
                    <i class="fas fa-undo"></i> Send back to Inspection
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

async function openDispatchModal(buyerOrderId) {
    if (!buyerOrderId) return;
    document.getElementById('dispatchOrderId').textContent = buyerOrderId;
    document.getElementById('dispatchBuyerOrderNo').value = '';
    document.getElementById('dispatchInvoiceNo').value = '';
    document.getElementById('dispatchChallanNo').value = '';
    document.getElementById('dispatchBody').innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:16px;">Loading...</td></tr>';
    document.getElementById('dispatchModal').classList.add('active');

    try {
        const r = await API.call('/fg-inventory/dispatch-data/' + encodeURIComponent(buyerOrderId));
        if (!r.success) {
            document.getElementById('dispatchBody').innerHTML = '<tr><td colspan="5" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + (r.message || 'Unknown') + '</td></tr>';
            return;
        }
        document.getElementById('dispatchBuyerOrderNo').value = r.buyerOrderNo || '';
        window._dispatchBuyerOrderId = buyerOrderId;
        renderDispatchRows(r.fgs || []);
    } catch (e) {
        document.getElementById('dispatchBody').innerHTML = '<tr><td colspan="5" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

function renderDispatchRows(fgs) {
    const tb = document.getElementById('dispatchBody');
    if (!fgs || fgs.length === 0) {
        tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:16px;">No FGs with available qty.</td></tr>';
        return;
    }
    let html = '';
    fgs.forEach((fg, idx) => {
        const roundedQty = Math.ceil(fg.fgQty || 0);
        html += `<tr data-fg-key="${fg.fgKey}" data-fg-qty="${fg.fgQty || 0}">
            <td style="text-align:center;">${idx + 1}</td>
            <td><strong>${fg.design || '—'}</strong></td>
            <td>${fg.color || '—'}</td>
            <td style="text-align:right;padding-right:12px;">${roundedQty}</td>
            <td style="text-align:right;padding-right:12px;"><input type="number" class="dispatch-qty" min="0" step="1" value="${roundedQty}" style="width:100%;max-width:120px;text-align:right;padding:6px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-input);color:var(--text-primary);font-size:13px;" oninput="validateDispatchQty(this)"></td>
        </tr>`;
    });
    tb.innerHTML = html;
}

function validateDispatchQty(input) {
    const row = input.closest('tr');
    const fgQty = parseFloat(row.dataset.fgQty) || 0;
    let v = parseFloat(input.value) || 0;
    if (v < 0) { v = 0; input.value = 0; return; }
    if (v > fgQty + 0.01) {
        showToast('Dispatch Qty cannot exceed FG Qty (' + Math.ceil(fgQty) + ')', 'error');
        input.value = Math.ceil(fgQty);
    }
}

function closeDispatchModal() {
    document.getElementById('dispatchModal').classList.remove('active');
}

async function submitDispatch() {
    const buyerOrderId = window._dispatchBuyerOrderId;
    if (!buyerOrderId) { showToast('No order loaded', 'error'); return; }

    const invoiceNo = document.getElementById('dispatchInvoiceNo').value.trim();
    const challanNo = document.getElementById('dispatchChallanNo').value.trim();

    const rows = document.querySelectorAll('#dispatchBody tr[data-fg-key]');
    const payload = [];
    let hasError = false;
    rows.forEach(row => {
        const fgKey = row.dataset.fgKey;
        const fgQty = parseFloat(row.dataset.fgQty) || 0;
        const qty = parseFloat(row.querySelector('.dispatch-qty').value) || 0;
        if (qty <= 0) return;
        if (qty > fgQty + 0.01) {
            showToast(fgKey + ': Dispatch qty exceeds FG qty', 'error');
            hasError = true;
            return;
        }
        payload.push({ fgKey, fgQty, dispatchQty: qty });
    });

    if (hasError) return;
    if (payload.length === 0) { showToast('No quantities to dispatch', 'error'); return; }

    if (!confirm('Dispatch ' + payload.length + ' FG line(s)?')) return;

    const btn = document.getElementById('dispatchSubmitBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Dispatching...';

    try {
        const r = await API.call('/fg-inventory/dispatch', 'POST', {
            buyer_order_id: buyerOrderId,
            invoice_no: invoiceNo,
            challan_no: challanNo,
            dispatched_by: 'admin',
            rows: payload
        });
        if (r.success) {
            showToast(r.message || 'Dispatched successfully', 'success');
            closeDispatchModal();
            refreshFGInventory();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-truck"></i> Dispatch';
    }
}

async function sendBackToInspection(buyerOrderId) {
    if (!buyerOrderId) return;
    if (!confirm('Send this buyer order back to FG Inspection?\nThis will move the token backward by one stage.')) return;
    showToast('Sending back...', 'info');
    try {
        const r = await API.call('/fg-inventory/send-back', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || 'Sent back to FG Inspection', 'success');
            refreshFGInventory();
            refreshFGInspections();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function dispatchFG(fgKey, orderId) {
    const qty = prompt(`Enter quantity to dispatch for ${fgKey}:`, '0');
    if (!qty) return;
    const quantity = parseFloat(qty);
    if (isNaN(quantity) || quantity <= 0) {
        showToast('Invalid quantity', 'error');
        return;
    }
    if (!confirm(`Dispatch ${quantity} units of ${fgKey}?`)) return;
    showToast('Dispatching...', 'info');
    try {
        const r = await API.call('/fg-inventory/dispatch', 'POST', { fg_key: fgKey, buyer_order_id: orderId, quantity: quantity });
        if (r.success) {
            showToast(r.message, 'success');
            refreshFGInventory();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function returnFG(fgKey, orderId) {
    const qty = prompt(`Enter quantity to return for ${fgKey}:`, '0');
    if (!qty) return;
    const quantity = parseFloat(qty);
    if (isNaN(quantity) || quantity <= 0) {
        showToast('Invalid quantity', 'error');
        return;
    }
    if (!confirm(`Return ${quantity} units of ${fgKey} to FG Inspection?`)) return;
    showToast('Returning...', 'info');
    try {
        const r = await API.call('/fg-inventory/return', 'POST', { fg_key: fgKey, buyer_order_id: orderId, quantity: quantity });
        if (r.success) {
            showToast(r.message, 'success');
            refreshFGInventory();
            refreshFGInspections();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 20: REPORTS
// ==============================================================

async function loadBuyerOrderStatusReport() {
    console.log('[DEBUG] loadBuyerOrderStatusReport called');
    const tb = document.getElementById('report-buyer_status-body');
    console.log('[DEBUG] tbody element:', tb);
    if (!tb) return;
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">Loading...</td></tr>';

    try {
        const r = await API.call('/reports/buyer-order-status');
        console.log('[DEBUG] API response:', r);
        const counters = r.counters || {};
        const orders = r.orders || [];

        // Update counters
        const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        setTxt('rptTotalBuyerOrders', counters.totalBuyerOrders || 0);
        setTxt('rptBuyerOrderQty', Math.ceil(counters.buyerOrderQty || 0));
        setTxt('rptFgInventoryQty', Math.ceil(counters.fgInventoryQty || 0));
        setTxt('rptDispatchedQty', Math.ceil(counters.dispatchedQty || 0));
        setTxt('rptBalanceAfterDispatch', Math.ceil(counters.balanceAfterDispatch || 0));

        // Apply filters
        const search = (document.getElementById('filter-buyer-search')?.value || '').toLowerCase();
        const stageFilter = document.getElementById('filter-buyer-status')?.value || 'ALL';

        let filtered = orders;
        if (search) {
            filtered = filtered.filter(o =>
                (o.buyer || '').toLowerCase().includes(search) ||
                (o.buyerOrderNo || '').toLowerCase().includes(search) ||
                (o.buyerOrderId || '').toLowerCase().includes(search)
            );
        }
        if (stageFilter && stageFilter !== 'ALL') {
            filtered = filtered.filter(o => o.status === stageFilter);
        }

        reportDataCache['BUYER_ORDER_STATUS'] = filtered;
        renderBuyerOrderStatusReport(filtered);
    } catch (e) {
        tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ea4335;padding:16px;">Error: ' + e.message + '</td></tr>';
    }
}

function renderBuyerOrderStatusReport(orders) {
    const tb = document.getElementById('report-buyer_status-body');
    if (!tb) return;
    if (!orders || orders.length === 0) {
        tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#62748e;padding:16px;">No orders found.</td></tr>';
        return;
    }
    let html = '';
    orders.forEach(o => {
        const fgList = (o.fgDetails || []).map(fg => `${fg.design}; ${fg.color}`).join('&#10;');
        const qtyList = (o.fgDetails || []).map(fg => `${fg.design}; ${fg.color}: ${Math.ceil(fg.qty)}`).join('&#10;');
        const fgCountCell = fgList
            ? `<strong title="${fgList}" style="cursor:help;border-bottom:1px dotted #888;">${o.fgCount || 0}</strong>`
            : `<strong>${o.fgCount || 0}</strong>`;
        const qtyCell = qtyList
            ? `<strong title="${qtyList}" style="cursor:help;border-bottom:1px dotted #888;">${Math.ceil(o.quantity || 0)}</strong>`
            : `<strong>${Math.ceil(o.quantity || 0)}</strong>`;

        const stageBadge = getStageBadgeClass(o.status);
        html += `<tr>
            <td><strong>${o.buyer || '—'}</strong></td>
            <td>${o.buyerOrderNo || '—'}</td>
            <td>${safeDate(o.orderDate)}</td>
            <td>${fgCountCell}</td>
            <td>${qtyCell}</td>
            <td><span class="badge-status ${stageBadge}">${o.status || '—'}</span></td>
            <td>
                <button class="btn btn-primary btn-xs" onclick="printBuyerOrderReport('${o.buyerOrderId}')">
                    <i class="fas fa-print"></i> Print
                </button>
            </td>
        </tr>`;
    });
    tb.innerHTML = html;
}

function getStageBadgeClass(stage) {
    const map = {
        'BUYER_ORDER': 'info',
        'BOM': 'primary',
        'COSTING_APPROVAL': 'warning',
        'RM_ORDER': 'info',
        'RM_INSPECTION': 'warning',
        'GRN': 'primary',
        'INTERNAL_FG_ORDER': 'warning',
        'ISSUE_RM': 'partial',
        'FG_INSPECTION': 'warning',
        'FG_INVENTORY': 'success',
    };
    return map[stage] || 'info';
}

function printBuyerOrderReport(buyerOrderId) {
    if (!buyerOrderId) return;
    const order = (reportDataCache['BUYER_ORDER_STATUS'] || []).find(o => o.buyerOrderId === buyerOrderId);
    const currentStage = (order && order.status) ? order.status : 'BUYER_ORDER';
    const stages = [
        'BUYER_ORDER', 'BOM', 'COSTING_APPROVAL', 'RM_ORDER', 'RM_INSPECTION',
        'GRN', 'INTERNAL_FG_ORDER', 'ISSUE_RM', 'FG_INSPECTION', 'FG_INVENTORY'
    ];
    const labels = {
        'BUYER_ORDER': 'Buyer Order',
        'BOM': 'BOM',
        'COSTING_APPROVAL': 'Costing Approval',
        'RM_ORDER': 'RM Order (PO)',
        'RM_INSPECTION': 'RM Inspection',
        'GRN': 'GRN',
        'INTERNAL_FG_ORDER': 'Internal FG Order',
        'ISSUE_RM': 'Issue RM',
        'FG_INSPECTION': 'FG Inspection',
        'FG_INVENTORY': 'FG Inventory',
        'DISPATCH': 'Dispatch'
    };
    const idx = stages.indexOf(currentStage);
    const reached = idx >= 0 ? stages.slice(0, idx + 1) : [currentStage];

    const existing = document.getElementById('printStageModal');
    if (existing) existing.remove();

    let html = '<div id="printStageModal" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:99999;">';
    html += '<div style="background:var(--bg-card);border-radius:12px;padding:24px 28px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto;border:1px solid var(--border-color);box-shadow:0 20px 60px rgba(0,0,0,0.35);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">';
    html += '<h3 style="margin:0;color:var(--text-primary);"><i class="fas fa-print" style="color:#2a6df4;"></i> Print — ' + buyerOrderId + '</h3>';
    html += '<button onclick="document.getElementById(\'printStageModal\').remove()" style="background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-muted);">×</button>';
    html += '</div>';
    html += '<p class="text-muted" style="font-size:12px;margin:0 0 14px 0;">Current stage: <strong>' + (labels[currentStage] || currentStage) + '</strong>. Select a stage to print.</p>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">';
    reached.forEach(function(s) {
        html += '<button class="btn btn-primary" style="padding:10px 12px;font-size:13px;width:100%;" onclick="window.open(\'/reports/print/' + s + '/' + buyerOrderId + '\', \'_blank\')"><i class="fas fa-file-alt"></i> ' + (labels[s] || s) + '</button>';
    });
    if (order && order.dispatched) {
        html += '<button class="btn btn-success" style="padding:10px 12px;font-size:13px;width:100%;" onclick="window.open(\'/reports/print/DISPATCH/' + buyerOrderId + '\', \'_blank\')"><i class="fas fa-truck"></i> Dispatch</button>';
    }
    html += '</div></div></div>';

    const div = document.createElement('div');
    div.innerHTML = html;
    const node = div.firstElementChild;
    node.addEventListener('click', function(e) { if (e.target === node) node.remove(); });
    document.body.appendChild(node);
}

async function loadReports() {
    showToast('Loading reports...', 'info');

    // New buyer order status report
    loadBuyerOrderStatusReport();

    // Legacy reports (RM Stock, RM Ordered)
    const reportTypes = ['RM_STOCK', 'RM_ORDERED'];

    try {
        const filters = await API.getReportFilters();
        ERP_STATE.reportFilters = filters;
        const supplierSelects = ['filter-stock-supplier', 'filter-ordered-supplier'];
        supplierSelects.forEach(id => {
            const sel = document.getElementById(id);
            if (sel) {
                const current = sel.value;
                sel.innerHTML = '<option value="ALL">All Suppliers</option>';
                if (filters.suppliers) {
                    filters.suppliers.forEach(s => sel.innerHTML += `<option value="${s}">${s}</option>`);
                }
                if (current) sel.value = current;
            }
        });
    } catch (e) {
        showToast('Error loading filters: ' + e.message, 'error');
    }

    reportTypes.forEach(async (type) => {
        const filters = getReportFiltersForType(type);
        try {
            const data = await API.getReportData(type, filters);
            reportDataCache[type] = data || [];
            renderReport(type, data);
        } catch (e) {
            showToast(`Error loading ${type}: ${e.message}`, 'error');
        }
    });
    setTimeout(() => showToast('Reports loaded', 'success'), 500);
}

function getReportFiltersForType(type) {
    const filters = {};
    switch (type) {
        case 'BUYER_ORDER_STATUS':
            filters.status = document.getElementById('filter-buyer-status')?.value || 'ALL';
            filters.dateFrom = document.getElementById('filter-buyer-from')?.value || '';
            filters.dateTo = document.getElementById('filter-buyer-to')?.value || '';
            break;
        case 'RM_STOCK':
            filters.supplier = document.getElementById('filter-stock-supplier')?.value || 'ALL';
            filters.fgKey = document.getElementById('filter-stock-search')?.value || '';
            filters.status = document.getElementById('filter-stock-status')?.value || 'ALL';
            break;
        case 'RM_ORDERED':
            filters.supplier = document.getElementById('filter-ordered-supplier')?.value || 'ALL';
            filters.status = document.getElementById('filter-ordered-status')?.value || 'ALL';
            filters.dateFrom = document.getElementById('filter-ordered-from')?.value || '';
            filters.dateTo = document.getElementById('filter-ordered-to')?.value || '';
            break;
    }
    return filters;
}

function switchReportTab(tabName) {
    document.querySelectorAll('.report-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.report-tab[data-report="${tabName}"]`)?.classList.add('active');
    document.querySelectorAll('.report-container').forEach(c => c.classList.remove('active'));
    document.getElementById(`report-${tabName}`)?.classList.add('active');

    if (tabName === 'buyer_status') {
        loadBuyerOrderStatusReport();
        return;
    }

    const typeMap = { rm_stock: 'RM_STOCK', rm_ordered: 'RM_ORDERED' };
    const type = typeMap[tabName];
    if (!type) return;
    const data = reportDataCache[type];
    if (data && data.length > 0) {
        renderReport(type, data);
    } else {
        filterReport(tabName);
    }
}

async function filterReport(tabName) {
    if (tabName === 'buyer_status') {
        loadBuyerOrderStatusReport();
        return;
    }
    const typeMap = { rm_stock: 'RM_STOCK', rm_ordered: 'RM_ORDERED' };
    const type = typeMap[tabName];
    const filters = getReportFiltersForType(type);
    showToast('Filtering...', 'info');
    try {
        const data = await API.getReportData(type, filters);
        reportDataCache[type] = data || [];
        renderReport(type, data);
        showToast(`Filtered: ${data.length} records`, 'success');
    } catch (e) {
        showToast('Error filtering: ' + e.message, 'error');
    }
}

function renderReport(type, data) {
    // Compute counters per report type
    if (type === 'RM_STOCK') {
        let totalItems = 0, totalQty = 0, outOfStock = 0, lowStock = 0;
        (data || []).forEach(r => {
            totalItems++;
            totalQty += (r.stock || 0);
            if ((r.stock || 0) <= 0) outOfStock++;
            else if ((r.stock || 0) < 10) lowStock++;
        });
        const el1 = document.getElementById('rptRmStockTotalItems'); if (el1) el1.textContent = totalItems;
        const el2 = document.getElementById('rptRmStockTotalQty'); if (el2) el2.textContent = Math.ceil(totalQty);
        const el3 = document.getElementById('rptRmStockOutOfStock'); if (el3) el3.textContent = outOfStock;
        const el4 = document.getElementById('rptRmStockLowStock'); if (el4) el4.textContent = lowStock;
    }
    if (type === 'RM_ORDERED') {
        let totalPOs = 0, totalQty = 0, totalAmount = 0;
        let draft = 0, processed = 0, completed = 0;
        (data || []).forEach(r => {
            totalPOs++;
            totalQty += (r.totalQty || 0);
            totalAmount += (r.totalAmount || 0);
            const s = (r.status || '').toUpperCase();
            if (s === 'DRAFT') draft++;
            else if (s === 'PROCESSED') processed++;
            else if (s === 'COMPLETED') completed++;
        });
        const el1 = document.getElementById('rptRmOrderedTotalPOs'); if (el1) el1.textContent = totalPOs;
        const el2 = document.getElementById('rptRmOrderedTotalQty'); if (el2) el2.textContent = Math.ceil(totalQty);
        const el3 = document.getElementById('rptRmOrderedTotalAmount'); if (el3) el3.textContent = '₹' + Math.ceil(totalAmount);
        const el4 = document.getElementById('rptRmOrderedByStatus'); if (el4) el4.textContent = draft + ' / ' + processed + ' / ' + completed;
    }
    
    const idMap = {
        'RM_STOCK': 'report-rm_stock-body',
        'RM_ORDERED': 'report-rm_ordered-body'
    };
    const tbody = document.getElementById(idMap[type]);
    if (!tbody) return;
    if (!data || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:#62748e;padding:16px;">No data found</td></tr>';
        return;
    }
    let html = '';
    const searchVal = getSearchValueForType(type);

    data.forEach(row => {
        if (searchVal) {
            const rowStr = JSON.stringify(row).toLowerCase();
            if (!rowStr.includes(searchVal.toLowerCase())) return;
        }
        switch (type) {
            case 'RM_STOCK':
                const stockStatus = row.stock > 0 ? (row.stock < 10 ? 'warning' : 'success') : 'danger';
                // FG Key cell: count of live contributing FGs. Hover lists
                // each FG (design|color) with its consumption for this RM.
                const fgCount = row.fgCount || 0;
                const breakdown = (row.fgBreakdown || []).map(fg =>
                    `${fg.buyerName || ''} | ${fg.buyerOrderNo || ''} | ${fg.design || ''} | ${fg.color || ''}  (cons ${(fg.consumption || 0).toFixed(4)}, qty ${(fg.qty || 0).toFixed(2)})`
                ).join('&#10;');
                const fgCell = breakdown
                    ? `<strong title="${breakdown}" style="cursor:help;border-bottom:1px dotted #888;">${fgCount}</strong>`
                    : `<strong>${fgCount}</strong>`;
                html += `<tr>
                    <td>${fgCell}</td>
                    <td><strong>${row.itemNo || '—'}</strong></td>
                    <td>${row.itemName || '—'}</td>
                    <td>${row.garmentSize || '—'}</td>
                    <td>${row.color || '—'}</td>
                    <td>${row.supplier || '—'}</td>
                    <td>Rs.${(row.rate || 0).toFixed(2)}</td>
                    <td>${(row.grnReceived || 0).toFixed(2)}</td>
                    <td>${(row.issued || 0).toFixed(2)}</td>
                    <td><span class="text-${stockStatus}">${(row.stock || 0).toFixed(2)}</span></td>
                    <td>${(row.required || 0).toFixed(2)}</td>
                </tr>`;
                break;
            case 'RM_ORDERED':
                const poStatus = row.status || 'DRAFT';
                const poStatusClass = poStatus.toLowerCase();
                html += `<tr>
                    <td><strong>${row.poToken || '—'}</strong></td>
                    <td>${row.supplier || '—'}</td>
                    <td>${row.orderDate ? new Date(row.orderDate).toLocaleDateString('en-IN') : '—'}</td>
                    <td>${row.fgKeys ? row.fgKeys.join(', ') : 'N/A'}</td>
                    <td>${(row.totalQty || 0).toFixed(2)}</td>
                    <td>Rs.${(row.totalAmount || 0).toFixed(2)}</td>
                    <td><span class="status-badge ${poStatusClass}">${poStatus}</span></td>
                </tr>`;
                break;
        }
    });
    tbody.innerHTML = html || '<tr><td colspan="10" style="text-align:center;color:#62748e;padding:16px;">No matching records</td></tr>';
}

function getSearchValueForType(type) {
    const idMap = {
        'BUYER_ORDER_STATUS': 'filter-buyer-search',
        'RM_STOCK': 'filter-stock-search',
        'RM_ORDERED': 'filter-ordered-search'
    };
    const el = document.getElementById(idMap[type]);
    return el ? el.value : '';
}

function exportReportCSV(tabName) {
    const typeMap = { buyer_status: 'BUYER_ORDER_STATUS', rm_stock: 'RM_STOCK', rm_ordered: 'RM_ORDERED' };
    const type = typeMap[tabName];
    const data = reportDataCache[type] || [];
    if (data.length === 0) {
        showToast('No data to export', 'error');
        return;
    }
    const headers = Object.keys(data[0]);
    let csv = headers.join(',') + '\n';
    data.forEach(row => {
        const values = headers.map(h => {
            let val = row[h];
            if (typeof val === 'string' && val.includes(',')) val = `"${val}"`;
            if (val instanceof Date) val = val.toISOString();
            if (val === null || val === undefined) val = '';
            return val;
        });
        csv += values.join(',') + '\n';
    });
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${type}_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('CSV exported', 'success');
}

function printReport(tabName) {
    const content = document.getElementById(`report-${tabName}-table`);
    if (!content) return;
    const printWindow = window.open('', '_blank');
    const html = `<html>
        <head><title>Sneha ERP - ${tabName}</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            table { width: 100%; border-collapse: collapse; }
            th { background: #f0f4fe; padding: 8px; text-align: left; }
            td { padding: 6px 8px; border-bottom: 1px solid #ddd; }
            .status-badge { padding: 2px 8px; border-radius: 12px; font-size: 10px; }
            .status-badge.completed { background: #d4edda; }
            .status-badge.partial { background: #fff3cd; }
            .status-badge.draft { background: #cce5ff; }
            .status-badge.closed { background: #d1ecf1; }
            .text-success { color: #34a853; }
            .text-danger { color: #ea4335; }
            .text-warning { color: #fbbc04; }
        </style>
    </head>
    <body>
        <h2>Sneha Creations ERP - ${tabName}</h2>
        <p>Generated: ${new Date().toLocaleString()}</p>
        ${content.innerHTML}
    </body></html>`;
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.onload = function () { printWindow.print(); };
}

// ==============================================================
// SECTION 21: RM SUPPLIER MODAL
// ==============================================================

function openRMSupplierModal(cb) {
    storedBOMState = {
        items: JSON.parse(JSON.stringify(ERP_STATE.bomItemsData)),
        fgKey: ERP_STATE.bomCurrentFGKey,
        isOpen: ERP_STATE.isBomModalOpen
    };
    rmSupplierCb = cb || null;
    document.getElementById('rmSupplierModal').classList.add('active');
    ['newRMSupplierName', 'newRMSupplierGST', 'newRMSupplierAddress', 'newRMSupplierContactPerson', 'newRMSupplierContactNo', 'newRMSupplierPaymentTerm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
}

function closeRMSupplierModal() {
    rmSupplierCb = null;
    document.getElementById('rmSupplierModal').classList.remove('active');
    if (storedBOMState) {
        ERP_STATE.bomItemsData = storedBOMState.items;
        ERP_STATE.bomCurrentFGKey = storedBOMState.fgKey;
        ERP_STATE.isBomModalOpen = storedBOMState.isOpen;
        if (ERP_STATE.isBomModalOpen && document.getElementById('bomModal').classList.contains('active')) {
            // renderBOMItems function would be called here if it exists
        }
        storedBOMState = null;
    }
}

async function addNewRMSupplier() {
    const data = {
        name: document.getElementById('newRMSupplierName').value.trim(),
        gst_no: document.getElementById('newRMSupplierGST').value.trim(),
        address: document.getElementById('newRMSupplierAddress').value.trim(),
        contact_person: document.getElementById('newRMSupplierContactPerson').value.trim(),
        contact_no: document.getElementById('newRMSupplierContactNo').value.trim(),
        payment_term: document.getElementById('newRMSupplierPaymentTerm').value.trim()
    };
    if (!data.name) {
        showToast('Supplier name required', 'error');
        return;
    }
    try {
        const r = await API.addRMSupplier(data);
        if (r.success) {
            showToast('Supplier added', 'success');
            // Save the callback before closeRMSupplierModal nulls it
            const cb = rmSupplierCb;
            // Clear rmSupplierCb BEFORE close so it doesn't null our local ref
            rmSupplierCb = null;
            // Close the modal manually without clearing rmSupplierCb
            document.getElementById('rmSupplierModal').classList.remove('active');
            if (storedBOMState) {
                ERP_STATE.bomItemsData = storedBOMState.items;
                ERP_STATE.bomCurrentFGKey = storedBOMState.fgKey;
                ERP_STATE.isBomModalOpen = storedBOMState.isOpen;
                storedBOMState = null;
            }
            // Refresh datalists AND Master Party
            refreshSupplierDatalists();
            refreshMasterParty();
            // Fire the callback to populate the RM item input
            if (cb) {
                cb(data.name);
            }
        } else {
            showToast(r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function openRMSupplierModalForAdd() {
    var modal = document.getElementById('rmSupplierModal');
    if (!modal) { showToast('Supplier modal not found', 'error'); return; }
    modal.classList.add('active');
    ['newRMSupplierName','newRMSupplierGST','newRMSupplierAddress','newRMSupplierContactPerson','newRMSupplierContactNo','newRMSupplierPaymentTerm'].forEach(function(id) {
        var el = document.getElementById(id); if (el) el.value = '';
    });
    rmSupplierCb = function(name) {
        document.getElementById('newRMSupplier').value = name;
        showToast('Supplier "' + name + '" added and selected', 'success');
    };
}

function openEditRMSupplierModal() {
    var modal = document.getElementById('rmSupplierModal');
    if (!modal) { showToast('Supplier modal not found', 'error'); return; }
    modal.classList.add('active');
    ['newRMSupplierName','newRMSupplierGST','newRMSupplierAddress','newRMSupplierContactPerson','newRMSupplierContactNo','newRMSupplierPaymentTerm'].forEach(function(id) {
        var el = document.getElementById(id); if (el) el.value = '';
    });
    rmSupplierCb = function(name) {
        document.getElementById('editRMSupplier').value = name;
        showToast('Supplier "' + name + '" added and selected', 'success');
    };
}

// ==============================================================
// SECTION 22: MASTER PARTY
// ==============================================================

async function refreshMasterParty() {
    getUserRole();
    showToast('Loading parties...', 'info');
    try {
        const response = await fetch('/master/all', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        if (!response.ok) throw new Error('Failed to load parties');
        partiesData = await response.json();
        document.getElementById('partyCount').textContent = partiesData.length;
        renderMasterParty();
        showToast('Parties loaded', 'success');
    } catch (e) {
        showToast('Error loading parties: ' + e.message, 'error');
    }
}

function renderMasterParty() {
    const tb = document.getElementById('masterPartyBody');
    const filter = document.getElementById('partyFilterType')?.value || 'ALL';
    const search = document.getElementById('partySearch')?.value.toLowerCase() || '';
    let list = partiesData;
    if (filter !== 'ALL') list = list.filter(p => p.category === filter);
    if (search) list = list.filter(p => p.name.toLowerCase().includes(search) ||
        (p.contact_person && p.contact_person.toLowerCase().includes(search)));
    if (!list.length) {
        tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#62748e;padding:16px;">No parties found</td></tr>';
        return;
    }
    const isAdmin = currentUserRole === 'admin';
    tb.innerHTML = list.map(p => `
        <tr>
            <td><span style="font-size:11px;">${p.id}</span></td>
            <td><span class="badge-status ${p.category === 'BUYER' ? 'info' : 'warning'}">${p.category}</span></td>
            <td><strong>${p.name}</strong></td>
            <td>${p.gst_no || '—'}</td>
            <td>${p.contact_person || '—'}</td>
            <td>${p.contact_no || '—'}</td>
            <td>${p.email || '—'}</td>
            <td><span class="badge-status ${p.status === 'ACTIVE' ? 'success' : 'danger'}">${p.status}</span></td>
            <td>
                ${isAdmin ? `
                    <button class="btn btn-primary btn-xs" onclick="openEditPartyModal('${p.id}')">
                        <i class="fas fa-edit"></i> Edit
                    </button>
                    <button class="btn btn-warning btn-xs" onclick="togglePartyStatus('${p.id}')">
                        <i class="fas fa-${p.status === "ACTIVE" ? "pause" : "play"}"></i> ${p.status === "ACTIVE" ? "Deactivate" : "Activate"}
                    </button>
                ` : `
                    <span class="text-muted" style="font-size:10px;">View only</span>
                `}
            </td>
        </tr>
    `).join('');
}

function filterMasterParty() { renderMasterParty(); }

async function addNewParty() {
    const category = document.getElementById('newPartyCategory')?.value;
    const name = document.getElementById('newPartyName')?.value.trim();
    const gst_no = document.getElementById('newPartyGST')?.value.trim().toUpperCase();
    const address = document.getElementById('newPartyAddress')?.value.trim();
    const contact_person = document.getElementById('newPartyContactPerson')?.value.trim();
    const contact_no = document.getElementById('newPartyContactNo')?.value.trim();
    const email = document.getElementById('newPartyEmail')?.value.trim();
    const payment_term = document.getElementById('newPartyPaymentTerm')?.value.trim();

    if (!name) { showToast('Name is required', 'error'); return; }
    if (!gst_no) { showToast('GST is required', 'error'); return; }

    const data = { category, name, gst_no, address, contact_person, contact_no, email, payment_term };
    const endpoint = category === 'BUYER' ? '/master/buyers' : '/master/suppliers';
    showToast('Adding party...', 'info');
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast('Party added successfully', 'success');
            closeModal('addPartyModal');
            refreshMasterParty();
        } else {
            showToast(result.message || 'Error adding party', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function updateParty() {
    const id = document.getElementById('editPartyId')?.value;
    const name = document.getElementById('editPartyName')?.value.trim();
    const gst_no = document.getElementById('editPartyGST')?.value.trim().toUpperCase();
    const address = document.getElementById('editPartyAddress')?.value.trim();
    const contact_person = document.getElementById('editPartyContactPerson')?.value.trim();
    const contact_no = document.getElementById('editPartyContactNo')?.value.trim();
    const email = document.getElementById('editPartyEmail')?.value.trim();
    const payment_term = document.getElementById('editPartyPaymentTerm')?.value.trim();
    const status = document.getElementById('editPartyStatus')?.value;

    if (!name) { showToast('Name is required', 'error'); return; }
    const data = { name, gst_no, address, contact_person, contact_no, email, payment_term, status };
    showToast('Updating party...', 'info');
    try {
        const response = await fetch(`/master/${id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast('Party updated successfully', 'success');
            closeModal('editPartyModal');
            refreshMasterParty();
        } else {
            showToast(result.message || 'Error updating party', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function deleteParty(id) {
    if (!confirm('Delete this party?')) return;
    showToast('Deleting party...', 'info');
    try {
        const response = await fetch(`/master/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        const result = await response.json();
        if (result.success) {
            showToast('Party deleted', 'success');
            refreshMasterParty();
        } else {
            showToast(result.message || 'Error deleting party', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function openEditPartyModal(id) {
    const party = partiesData.find(p => p.id === id);
    if (!party) { showToast('Party not found', 'error'); return; }
    document.getElementById('editPartyId').value = party.id;
    document.getElementById('editPartyCategory').value = party.category;
    document.getElementById('editPartyName').value = party.name;
    document.getElementById('editPartyGST').value = party.gst_no || '';
    document.getElementById('editPartyAddress').value = party.address || '';
    document.getElementById('editPartyContactPerson').value = party.contact_person || '';
    document.getElementById('editPartyContactNo').value = party.contact_no || '';
    document.getElementById('editPartyEmail').value = party.email || '';
    document.getElementById('editPartyPaymentTerm').value = party.payment_term || '';
    document.getElementById('editPartyStatus').value = party.status || 'ACTIVE';
    openModal('editPartyModal');
}

async function editPartyWithAuth(id) {
    const password = prompt('Enter your password to edit this party:');
    if (!password) return;
    try {
        const authResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: 'admin@sneha.com', password: password })
        });
        if (!authResponse.ok) {
            showToast('Invalid password', 'error');
            return;
        }
        const party = partiesData.find(p => p.id === id);
        if (!party) { showToast('Party not found', 'error'); return; }
        document.getElementById('editPartyId').value = party.id;
        document.getElementById('editPartyCategory').value = party.category;
        document.getElementById('editPartyName').value = party.name;
        document.getElementById('editPartyGST').value = party.gst_no || '';
        document.getElementById('editPartyAddress').value = party.address || '';
        document.getElementById('editPartyContactPerson').value = party.contact_person || '';
        document.getElementById('editPartyContactNo').value = party.contact_no || '';
        document.getElementById('editPartyEmail').value = party.email || '';
        document.getElementById('editPartyPaymentTerm').value = party.payment_term || '';
        document.getElementById('editPartyStatus').value = party.status || 'ACTIVE';
        openModal('editPartyModal');
        showToast('Authenticated', 'success');
    } catch (e) {
        showToast('Authentication failed: ' + e.message, 'error');
    }
}

async function togglePartyStatus(id) {
    const password = prompt('Enter your password to change status:');
    if (!password) return;
    try {
        const authResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: 'admin@sneha.com', password: password })
        });
        if (!authResponse.ok) {
            showToast('Invalid password', 'error');
            return;
        }
        const party = partiesData.find(p => p.id === id);
        if (!party) { showToast('Party not found', 'error'); return; }
        const newStatus = party.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE';
        const data = {
            name: party.name,
            gst_no: party.gst_no,
            address: party.address,
            contact_person: party.contact_person,
            contact_no: party.contact_no,
            email: party.email,
            payment_term: party.payment_term,
            status: newStatus
        };
        const response = await fetch(`/master/${id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast(`Party ${newStatus.toLowerCase()}d`, 'success');
            refreshMasterParty();
        } else {
            showToast(result.message || 'Error updating status', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 23: RM INVENTORY
// ==============================================================

async function refreshRMInventory() {
    console.log("[FIND] refreshRMInventory called");
    showToast("Loading RM Inventory...", "info");
    try {
        const response = await fetch("/master/inventory/", {
            headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
        });
        if (!response.ok) throw new Error("Failed to load RM Inventory");
        rmInventoryData = await response.json();
        document.getElementById("inventoryCount").textContent = rmInventoryData.length;
        renderRMInventory();
        showToast("RM Inventory loaded", "success");
    } catch (e) {
        showToast("Error loading RM Inventory: " + e.message, "error");
    }
}

function renderRMInventory() {
    const tb = document.getElementById('rmInventoryBody');
    const filter = document.getElementById('rmInvFilter')?.value || 'ALL';
    const search = document.getElementById('rmInvSearch')?.value.toLowerCase() || '';
    let list = rmInventoryData;
    if (filter !== 'ALL') list = list.filter(item => item.category === filter);
    if (search) list = list.filter(item =>
        (item.id && item.id.toLowerCase().includes(search)) ||
        (item.name && item.name.toLowerCase().includes(search)) ||
        (item.color && item.color.toLowerCase().includes(search))
    );
    if (!list.length) {
        tb.innerHTML = '<tr><td colspan="11" style="text-align:center;color:#62748e;padding:16px;">No RM items found</td></tr>';
        return;
    }
    tb.innerHTML = list.map(item => {
        const stockVal = (item.stock || 0).toFixed(2);
        const breakdown = item.stock_by_size || '';
        const stockCell = breakdown
            ? `<strong title="${breakdown}" style="cursor:help;border-bottom:1px dotted #888;">${stockVal}</strong>`
            : `<strong>${stockVal}</strong>`;
        return `
        <tr>
            <td><strong>${item.id || '—'}</strong></td>
            <td><span class="badge-status info">${item.category || '—'}</span></td>
            <td>${item.name || '—'}</td>
            <td>${item.color || '—'}</td>
            <td>${item.size || '—'}</td>
            <td>Rs.${(item.rate || 0).toFixed(2)}</td>
            <td>${item.supplier || '—'}</td>
            <td>${stockCell}</td>
            <td>${item.uom || 'PCS'}</td>
            <td>${item.location || '—'}</td>
            <td>
                <button class="btn btn-primary btn-xs" onclick="editRMItem('${item.id}')">
                    <i class="fas fa-edit"></i> Edit
                </button>
            </td>
        </tr>
    `;}).join('');
}

function filterRMInventory() { renderRMInventory(); }

async function addRMItem() {
    const name = document.getElementById("newRMName")?.value.trim();
    const color = document.getElementById("newRMColor")?.value.trim();
    const size = document.getElementById("newRMSize")?.value.trim();
    const uom = document.getElementById("newRMUOM")?.value;
    const rate = parseFloat(document.getElementById("newRMRate")?.value) || 0;
    const supplier = document.getElementById("newRMSupplier")?.value.trim();
    const location = document.getElementById("newRMLocation")?.value.trim();
    const category = document.getElementById("newRMCat")?.value || "FABRIC";

    if (!name) { showToast("RM Name is required", "error"); return; }
    if (!color) { showToast("RM Color is required", "error"); return; }
    if (!size) { showToast("RM Size is required", "error"); return; }

    const data = { name, category, color, size, uom, rate, supplier, location };
    showToast("Adding RM Item...", "info");
    try {
        const r = await API.call("/master/inventory/", "POST", data);
        if (r.success) {
            showToast("RM Item added successfully", "success");
            closeModal("addRMItemModal");
            refreshRMInventory();
        } else {
            showToast(r.message || "Error adding RM Item", "error");
        }
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

async function editRMItem(id) {
    const password = prompt('Enter your password to edit this RM item:');
    if (!password) return;
    try {
        const authResponse = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: 'admin@sneha.com', password: password })
        });
        if (!authResponse.ok) {
            showToast('Invalid password', 'error');
            return;
        }
        const item = rmInventoryData.find(i => i.id === id);
        if (!item) { showToast('Item not found', 'error'); return; }
        document.getElementById('editRMItemId').value = item.id;
        document.getElementById('editRMItemIdDisplay').value = item.id;
        document.getElementById('editRMCat').value = item.category || 'FABRIC';
        document.getElementById('editRMName').value = item.name || '';
        document.getElementById('editRMColor').value = item.color || '';
        document.getElementById('editRMSize').value = item.size || '';
        document.getElementById('editRMUOM').value = item.uom || 'PCS';
        document.getElementById('editRMRate').value = item.rate || 0;
        document.getElementById('editRMSupplier').value = item.supplier || '';
        document.getElementById('editRMLocation').value = item.location || '';
        document.getElementById('editRMStatus').value = item.status || 'ACTIVE';
        openModal('editRMItemModal');
        showToast('Authenticated', 'success');
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function updateRMItem() {
    const id = document.getElementById("editRMItemId").value;
    const name = document.getElementById("editRMName").value.trim();
    const category = document.getElementById("editRMCat").value;
    const color = document.getElementById("editRMColor").value.trim();
    const size = document.getElementById("editRMSize").value.trim();
    const uom = document.getElementById("editRMUOM").value;
    const rate = parseFloat(document.getElementById("editRMRate").value) || 0;
    const supplier = document.getElementById("editRMSupplier").value.trim();
    const location = document.getElementById("editRMLocation").value.trim();
    const status = document.getElementById("editRMStatus").value;

    if (!name) { showToast("Name is required", "error"); return; }
    if (!color) { showToast("Color is required", "error"); return; }
    if (!size) { showToast("Size is required", "error"); return; }

    // Check if supplier has changed
    const currentItem = (rmInventoryData || []).find(i => i.id === id);
    const currentSupplier = currentItem ? (currentItem.supplier || '').trim() : '';
    const supplierChanged = supplier !== currentSupplier;

    let mode = 'in-place';
    if (supplierChanged && currentSupplier) {
        // Ask user: change in place OR create new RM ID
        const choice = confirm(
            'Supplier changed from "' + currentSupplier + '" to "' + supplier + '".\n\n' +
            'OK = Change supplier in place (same RM ID: ' + id + ')\n' +
            'Cancel = Create a NEW RM ID for this supplier variant (old RM ID retains old supplier)'
        );
        mode = choice ? 'in-place' : 'new-id';
    }

    if (mode === 'new-id') {
        // Create a new RM ID with the new supplier; old item stays unchanged
        showToast("Creating new RM ID for supplier variant...", "info");
        try {
            const newData = {
                name: name,
                category: category,
                color: color,
                size: size,
                uom: uom,
                rate: rate,
                supplier: supplier,
                location: location
            };
            const r = await API.call("/master/inventory/", "POST", newData);
            if (r.success) {
                showToast("New RM ID created: " + (r.id || ''), "success");
                closeModal("editRMItemModal");
                await refreshRMInventory();
            } else {
                showToast(r.message || "Error creating new RM ID", "error");
            }
        } catch (e) {
            showToast("Error: " + e.message, "error");
        }
        return;
    }

    // Default: update in place
    showToast("Updating RM item...", "info");
    try {
        const r = await API.call("/master/inventory/" + id, "PUT", { name, category, color, size, uom, rate, supplier, location, status });
        if (r.success) {
            showToast("RM Item updated", "success");
            closeModal("editRMItemModal");
            await refreshRMInventory();
        } else {
            showToast(r.message || "Error updating item", "error");
        }
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

function deleteRMItem(id) {
    if (!confirm('Delete RM item ' + id + '?')) return;
    rmInventoryData = rmInventoryData.filter(i => i.id !== id);
    renderRMInventory();
    showToast('RM item deleted', 'success');
}

// ==============================================================
// SECTION 24: UOM & CATEGORY FUNCTIONS
// ==============================================================

async function addNewUOM(selectId) {
    const newUom = prompt('Enter new UOM:');
    if (!newUom || !newUom.trim()) return;
    const uom = newUom.trim().toUpperCase();
    showToast('Adding UOM...', 'info');
    try {
        const response = await fetch('/utils/uoms', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ uom: uom })
        });
        const result = await response.json();
        if (result.success) {
            showToast(result.message, 'success');
            refreshUOMDropdowns();
        } else {
            showToast(result.message || 'Error', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function refreshSupplierDatalists() {
    try {
        var response = await fetch('/master/suppliers', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        var suppliers = await response.json();
        var datalistIds = ['supplierDatalist', 'supplierDatalistEdit', 'supplierDatalistNew'];
        datalistIds.forEach(function(id) {
            var dl = document.getElementById(id);
            if (!dl) return;
            dl.innerHTML = '';
            suppliers.forEach(function(s) {
                var opt = document.createElement('option');
                var name = s.name || s;
                opt.value = name;
                opt.textContent = name;
                dl.appendChild(opt);
            });
        });
    } catch(e) { console.error('Error refreshing supplier datalists:', e); }
}

async function refreshUOMDropdowns() {
    try {
        const response = await fetch('/utils/uoms', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        const uoms = await response.json();
        ['newRMUOM', 'editRMUOM'].forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const current = sel.value;
            sel.innerHTML = '';
            uoms.forEach(uom => {
                const opt = document.createElement('option');
                opt.value = uom;
                opt.textContent = uom;
                sel.appendChild(opt);
            });
            if (current && uoms.includes(current)) sel.value = current;
        });
    } catch (e) {
        console.error('Error refreshing UOM dropdowns:', e);
    }
}

function addNewCategoryToRM() {
    const newCategory = prompt('Enter new category name:');
    if (!newCategory || !newCategory.trim()) return;
    const catName = newCategory.trim().toUpperCase();
    const select = document.getElementById('newRMCat');
    const existing = Array.from(select.options).some(opt => opt.value === catName);
    if (existing) {
        showToast('Category already exists', 'warning');
        return;
    }
    const option = document.createElement('option');
    option.value = catName;
    option.textContent = catName;
    select.appendChild(option);
    select.value = catName;
    showToast('Category "' + catName + '" added', 'success');
}

function addNewCategoryToEditRM() {
    const newCategory = prompt('Enter new category name:');
    if (!newCategory || !newCategory.trim()) return;
    const catName = newCategory.trim().toUpperCase();
    const select = document.getElementById('editRMCat');
    const existing = Array.from(select.options).some(opt => opt.value === catName);
    if (existing) {
        showToast('Category already exists', 'warning');
        return;
    }
    const option = document.createElement('option');
    option.value = catName;
    option.textContent = catName;
    select.appendChild(option);
    select.value = catName;
    showToast('Category "' + catName + '" added', 'success');
}

// ==============================================================
// SECTION 25: KEYBOARD SHORTCUTS
// ==============================================================

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeBuyerModal();
        closeRMSupplierModal();
        closeProcessPOModal();
        closePOPreview();
        closeGRNModal();
        closeShortfallModal();
        closeIssueRMModal();
        closeBOMAssignment();
    }
});

// ==============================================================
// SECTION 26: CANCEL ORDER FUNCTIONS
// ==============================================================

async function cancelOrderAction() {
    const fgOrderSerial = ERP_STATE.currentFGOrderSerial;
    if (!fgOrderSerial) {
        showToast('No order to cancel', 'error');
        return;
    }
    if (!confirm(`[WARN] Are you sure you want to CANCEL the entire order: ${fgOrderSerial}?`)) return;
    showToast('Cancelling order...', 'info');
    try {
        const r = await API.cancelOrder({ fgOrderSerial });
        if (r.success) {
            showToast(r.message, 'success');
            document.getElementById('gridSection').style.display = 'none';
            generateAutoSerial();
            setDefaultDates();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function cancelRMOrder() {
    const supplier = document.getElementById('poModalSupplier').textContent.replace('Supplier: ', '').trim();
    if (!supplier) {
        showToast('No RM order to cancel', 'error');
        return;
    }
    const supplierData = ERP_STATE.rmOrdersData.find(o => o.supplier === supplier);
    if (!supplierData) {
        showToast('Supplier not found', 'error');
        return;
    }
    const fgKeys = supplierData.fgKeys || [];
    if (fgKeys.length === 0) {
        showToast('No FGs to cancel', 'error');
        return;
    }
    if (!confirm(`[WARN] Are you sure you want to cancel RM ORDER for ${supplier}?`)) return;
    showToast('Cancelling RM Order...', 'info');
    try {
        let allSuccess = true;
        for (const fgKey of fgKeys) {
            const r = await API.cancelStage({ fgKey, targetStage: 'RM_ORDER' });
            if (!r.success) allSuccess = false;
        }
        if (allSuccess) {
            showToast('RM Order cancelled successfully', 'success');
            closeProcessPOModal();
            refreshRMOrders();
            refreshGRNOrders();
        } else {
            showToast('Some FGs could not be cancelled', 'warning');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function cancelGRNOrder() {
    const poToken = document.getElementById('grnPOToken').textContent;
    if (!poToken) {
        showToast('No GRN to cancel', 'error');
        return;
    }
    if (!confirm(`[WARN] Are you sure you want to cancel GRN for PO: ${poToken}?`)) return;
    const typed = prompt('This will move the buyer order back to RM Order and undo ALL POs of this order.\nType CONFIRM to proceed:');
    if (typed !== 'CONFIRM') {
        showToast('GRN cancellation aborted', 'info');
        return;
    }
    showToast('Cancelling GRN...', 'info');
    try {
        const r = await API.cancelGRN(poToken, '');
        if (r.success) {
            showToast(r.message, 'success');
            closeGRNModal();
            refreshGRNOrders();
            refreshRMOrders();
            refreshIssueRMOrders();
        } else {
            showToast('Error: ' + r.message, 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function cancelBOM(buyerOrderId) {
    if (!confirm(`[WARN] Are you sure you want to CANCEL the BOM for order ${buyerOrderId}?\nThis will move the order back to Buyer Orders.`)) return;
    showToast('Cancelling BOM...', 'info');
    fetch('/bom/cancel', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + localStorage.getItem('access_token')
        },
        body: JSON.stringify({ buyer_order_id: buyerOrderId })
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            showToast(result.message, 'success');
            refreshBOMOrders();
            refreshBuyerOrders();
        } else {
            showToast('Error: ' + result.message, 'error');
        }
    })
    .catch(e => showToast('Error: ' + e.message, 'error'));
}

// ==============================================================
// SECTION 27: GST UPPERCASE & VALIDATION
// ==============================================================

document.addEventListener('DOMContentLoaded', function() {
    const gstInputs = document.querySelectorAll('#newPartyGST, #editPartyGST, #newGstNo, #newRMSupplierGST');
    gstInputs.forEach(input => {
        if (input) {
            input.addEventListener('input', function() {
                this.value = this.value.toUpperCase();
            });
            input.addEventListener('blur', function() {
                this.value = this.value.toUpperCase().trim();
            });
        }
    });
});

function validatePartyForm() {
    const name = document.getElementById('newPartyName').value.trim();
    const gst = document.getElementById('newPartyGST').value.trim();
    const contact = document.getElementById('newPartyContactPerson').value.trim();
    if (!name) { showToast('Name is required', 'error'); return false; }
    if (!gst) { showToast('GST Number is required', 'error'); return false; }
    if (!contact) { showToast('Contact Person is required', 'error'); return false; }
    return true;
}

const originalAddNewParty = window.addNewParty;
window.addNewParty = function() {
    if (!validatePartyForm()) return;
    originalAddNewParty();
};

// ==============================================================
// SECTION 28: DEBUG
// ==============================================================

async function debugFGStatus() {
    let fgKey = null;
    const bomRow = document.querySelector('#bomOrderBody tr:first-child');
    if (bomRow) {
        fgKey = bomRow.querySelector('td:first-child')?.textContent?.trim();
    }
    if (!fgKey) {
        const issueRow = document.querySelector('#issueRMOrderBody tr:first-child');
        if (issueRow) {
            fgKey = issueRow.querySelector('td:first-child')?.textContent?.trim();
        }
    }
    if (!fgKey) {
        showToast('No FG Key found. Load orders first.', 'error');
        return;
    }
    showToast('Checking status for: ' + fgKey, 'info');
    try {
        const result = await API.debugFGStatus(fgKey);
        let msg = '═══════════════════════════════════════\n     FG STATUS REPORT\n═══════════════════════════════════════\n';
        msg += 'FG Key: ' + result.fgKey + '\nCurrent Position: ' + result.currentPosition + '\nTotal Entries: ' + result.totalEntries + '\n───────────────────────────────────────\n';
        if (result.allStatuses) {
            for (const [module, status] of Object.entries(result.allStatuses)) {
                msg += module + ': ' + status + '\n';
            }
        }
        msg += '───────────────────────────────────────\n';
        if (result.entries && result.entries.length > 0) {
            msg += 'Recent Entries:\n';
            const recent = result.entries.slice(-5);
            for (const entry of recent) {
                msg += `  ${entry.activity}: ${entry.status} ${entry.size ? '| Size: ' + entry.size : ''} ${entry.qty ? '| Qty: ' + entry.qty : ''}\n`;
            }
        }
        msg += '═══════════════════════════════════════';
        alert(msg);
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ==============================================================
// SECTION 29: PAGE INITIALIZATION
// ==============================================================

document.addEventListener('DOMContentLoaded', function() {
    loadTheme();

    const savedModule = localStorage.getItem('activeModule');
    if (savedModule) {
        const navItem = document.querySelector(`.nav-item[data-module="${savedModule}"]`);
        if (navItem) {
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.module-content').forEach(c => c.classList.remove('active'));
            navItem.classList.add('active');
            const el = document.getElementById('module-' + savedModule);
            if (el) el.classList.add('active');
        }
    }

    refreshBuyerOrders();
    refreshBOMOrders();
    refreshApprovalOrders();
    refreshRMOrders();
    refreshRMInspections();
    refreshGRNOrders();
    refreshInternalFGOrders();
    refreshIssueRMOrders();
    refreshFGInspections();
    refreshFGInventory();
    refreshMasterParty();
    refreshRMInventory();
    refreshSupplierDatalists();
    loadBuyers();
    setDefaultDates();
    generateAutoSerial();
    console.log('[OK] Sneha Creations ERP v3.0 - 10-Stage Workflow');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', function() {
            const module = this.dataset.module;
            localStorage.setItem('activeModule', module);

            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            this.classList.add('active');

            document.querySelectorAll('.module-content').forEach(c => c.classList.remove('active'));
            const el = document.getElementById(`module-${module}`);
            if (el) el.classList.add('active');

            if (module === 'BUYER_ORDER') {
                loadBuyers();
                setDefaultDates();
                generateAutoSerial();
                document.getElementById('gridSection').style.display = 'none';
            } else if (module === 'BOM_COSTING') {
                refreshBOMOrders();
            } else if (module === 'COSTING_APPROVAL') {
                refreshApprovalOrders();
            } else if (module === 'RM_ORDER' || module === 'RW_ORDER') {
                refreshRMOrders();
            } else if (module === 'RM_INSPECTION' || module === 'RW_INSPECTION') {
                refreshRMInspections();
            } else if (module === 'GRN' || module === 'RW_GRN') {
                refreshGRNOrders();
            } else if (module === 'INTERNAL_FG_ORDER') {
                refreshInternalFGOrders();
            } else if (module === 'ISSUE_RM' || module === 'RW_ISSUE') {
                refreshIssueRMOrders();
            } else if (module === 'FG_INSPECTION') {
                refreshFGInspections();
            } else if (module === 'FG_INVENTORY') {
                refreshFGInventory();
            } else if (module === 'REPORTS') {
                loadReports();
            }
        });
    });
});

// ==============================================================
// SECTION 30: GLOBAL EXPOSURE
// ==============================================================

window.refreshMasterParty = refreshMasterParty;
window.renderMasterParty = renderMasterParty;
window.filterMasterParty = filterMasterParty;
window.addNewParty = addNewParty;
window.updateParty = updateParty;
window.deleteParty = deleteParty;
window.openEditPartyModal = openEditPartyModal;
window.editPartyWithAuth = editPartyWithAuth;
window.togglePartyStatus = togglePartyStatus;

window.refreshRMInventory = refreshRMInventory;
window.renderRMInventory = renderRMInventory;
window.filterRMInventory = filterRMInventory;
window.addRMItem = addRMItem;
window.editRMItem = editRMItem;
window.updateRMItem = updateRMItem;
window.deleteRMItem = deleteRMItem;

window.loadBuyers = loadBuyers;
window.loadBuyerDetails = loadBuyerDetails;
window.openBuyerModal = openBuyerModal;
window.closeBuyerModal = closeBuyerModal;
window.addNewBuyer = addNewBuyer;
window.setDefaultDates = setDefaultDates;
window.calculateLeadTime = calculateLeadTime;
window.generateAutoSerial = generateAutoSerial;
window.generateGrid = generateGrid;
window.renderGrid = renderGrid;
window.saveOrder = saveOrder;
window.refreshBuyerOrders = refreshBuyerOrders;
window.renderBuyerOrders = renderBuyerOrders;
window.openOrderActions = openOrderActions;
window.cancelBuyerOrder = cancelBuyerOrder;
window.printOrder = printOrder;
window.editBuyerOrder = editBuyerOrder;
window.saveEditOrder = saveEditOrder;
window.addEditFGRow = addEditFGRow;
window.removeEditFGRow = removeEditFGRow;
window.loadEditBuyerDetails = loadEditBuyerDetails;
window.generateEditGrid = generateEditGrid;
window.renderEditGrid = renderEditGrid;
window.processOrderToStage = processOrderToStage;

window.refreshBOMOrders = refreshBOMOrders;
window.openBOMModalForOrder = openBOMModalForOrder;
window.cancelBOM = cancelBOM;
window.editBOMModal = editBOMModal;
window.closeBOMAssignment = closeBOMAssignment;
window.saveBOMAssignment = saveBOMAssignment;
window.addBOMRowToFG = addBOMRowToFG;
window.openSupplierModalForBOM = openSupplierModalForBOM;
window.submitBOMForApproval = submitBOMForApproval;

window.refreshApprovalOrders = refreshApprovalOrders;
window.openCostingApprovalModal = openCostingApprovalModal;
window.submitCostingDecision = submitCostingDecision;

window.refreshRMOrders = refreshRMOrders;
window.renderRMOrders = renderRMOrders;
window.openProcessPOModal = openProcessPOModal;
window.confirmProcessRMOrder = confirmProcessRMOrder;
window.openProcessPOModal = openProcessPOModal;
window.closeProcessPOModal = closeProcessPOModal;
window.renderPOItems = renderPOItems;
window.toggleGroup = toggleGroup;
window.toggleAllItems = toggleAllItems;
window.updateGroupCGST = updateGroupCGST;
window.updateGroupIGST = updateGroupIGST;
window.updatePOItems = updatePOItems;
window.generatePO = generatePO;
window.openPOPreview = openPOPreview;
window.closePOPreview = closePOPreview;
window.savePOAction = savePOAction;
window.processPOFromPreview = processPOFromPreview;

window.refreshRMInspections = refreshRMInspections;
window.renderRMInspections = renderRMInspections;
window.passRMInspection = passRMInspection;
window.failRMInspection = failRMInspection;
window.cancelRMInspectionOrder = cancelRMInspectionOrder;

window.refreshGRNOrders = refreshGRNOrders;
window.renderGRNOrders = renderGRNOrders;
window.openGRNPOListModal = openGRNPOListModal;
window.closeGRNPOListModal = closeGRNPOListModal;
window.openGRNInwardModal = openGRNInwardModal;
window.closeGRNInwardModal = closeGRNInwardModal;
window.printPOForRow = printPOForRow;
window.exportPOToExcel = exportPOToExcel;
window.saveGRNInward = saveGRNInward;
window.recalcGRNInwardRow = recalcGRNInwardRow;
window.openGRNModal = openGRNModal;
window.closeGRNModal = closeGRNModal;
window.saveGRN = saveGRN;
window.cancelGRNFromModal = cancelGRNFromModal;
window.refreshShortfalls = refreshShortfalls;
window.closeShortfallModal = closeShortfallModal;

window.refreshInternalFGOrders = refreshInternalFGOrders;
window.renderInternalFGOrders = renderInternalFGOrders;
window.openInternalFGModal = openInternalFGModal;
window.recalcIFGRow = recalcIFGRow;
window.updateIFGSummary = updateIFGSummary;
window.submitFactoryOrder = submitFactoryOrder;
window.processInternalFG = processInternalFG;
window.cancelInternalFG = cancelInternalFG;
window.cancelInternalFGBuyerOrder = cancelInternalFGBuyerOrder;
window.submitIFGCancel = submitIFGCancel;

window.refreshIssueRMOrders = refreshIssueRMOrders;
window.renderIssueRMOrders = renderIssueRMOrders;
window.openIssueRMBuyerModal = openIssueRMBuyerModal;
window.closeIssueRMBuyerModal = closeIssueRMBuyerModal;
window.renderIssueRMGrids = renderIssueRMGrids;
window.validateIssueRMQty = validateIssueRMQty;
window.saveAllIssueRM = saveAllIssueRM;
window.cancelIssueRMOrder = cancelIssueRMOrder;

window.refreshFGInspections = refreshFGInspections;
window.renderFGInspections = renderFGInspections;
window.inspectBuyerOrder = inspectBuyerOrder;
window.cancelFGInspection = cancelFGInspection;
window.closeFGInspectionModal = closeFGInspectionModal;
window.renderFGInspectionRows = renderFGInspectionRows;
window.validatePresentedQty = validatePresentedQty;
window.validateInspectedQty = validateInspectedQty;
window.submitFGInspection = submitFGInspection;

window.refreshFGInventory = refreshFGInventory;
window.renderFGInventory = renderFGInventory;
window.sendBackToInspection = sendBackToInspection;
window.openDispatchModal = openDispatchModal;
window.closeDispatchModal = closeDispatchModal;
window.renderDispatchRows = renderDispatchRows;
window.validateDispatchQty = validateDispatchQty;
window.submitDispatch = submitDispatch;

window.loadReports = loadReports;
window.loadBuyerOrderStatusReport = loadBuyerOrderStatusReport;
window.renderBuyerOrderStatusReport = renderBuyerOrderStatusReport;
window.printBuyerOrderReport = printBuyerOrderReport;
window.switchReportTab = switchReportTab;
window.filterReport = filterReport;
window.exportReportCSV = exportReportCSV;
window.printReport = printReport;

window.openModal = openModal;
window.closeModal = closeModal;

window.toggleTheme = toggleTheme;
window.loadTheme = loadTheme;
window.logout = logout;

window.filterTable = filterTable;
window.showToast = showToast;
window.debugFGStatus = debugFGStatus;
window.cancelStageAction = cancelStageAction;
window.cancelOrderAction = cancelOrderAction;
window.cancelRMOrder = cancelRMOrder;
window.cancelGRNOrder = cancelGRNOrder;
window.removeBOMRow = removeBOMRow;
window.addNewUOM = addNewUOM;
window.refreshUOMDropdowns = refreshUOMDropdowns;
window.openRMSupplierModalForAdd = openRMSupplierModalForAdd;
window.openEditRMSupplierModal = openEditRMSupplierModal;
window.refreshSupplierDatalists = refreshSupplierDatalists;
window.addNewCategoryToRM = addNewCategoryToRM;
window.addNewCategoryToEditRM = addNewCategoryToEditRM;
window.openOutwardOrders = openOutwardOrders;
window.cancelRMOrderFromCard = cancelRMOrderFromCard;

console.log('[OK] Sneha Creations ERP v3.0 - All functions exposed globally');async function refreshApprovalOrders() {
    showToast("Loading approval orders...", "info");
    const tb = document.getElementById("approvalOrderBody");
    if (!tb) return;
    try {
        const response = await fetch("/approval/orders", {
            headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
        });
        if (!response.ok) throw new Error("Failed to load approval orders");
        const orders = await response.json();
        if (!orders || orders.length === 0) {
            tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:16px;">No orders pending approval.</td></tr>';
            document.getElementById("approvalCount").textContent = "0";
            return;
        }
        let html = "";
        orders.forEach(order => {
            const statusBadge = order.status === "PENDING" ? "warning" : (order.status === "APPROVED" ? "success" : "danger");
            html += '<tr>';
            html += '<td><strong>' + (order.buyerOrderId || "—") + '</strong></td>';
            html += '<td>' + (order.buyerName || "—") + '</td>';
            html += '<td>' + (order.buyerOrderNo || "—") + '</td>';
            html += '<td><span class="badge-status info">' + (order.totalFGs || 0) + '</span></td>';
            html += '<td><span class="badge-status ' + statusBadge + '">' + (order.status || "PENDING") + '</span></td>';
            html += '<td><button class="btn btn-primary btn-sm" onclick="openCostingApprovalModal(\'' + order.buyerOrderId + '\')"><i class="fas fa-eye"></i> Review</button></td>';
            html += '</tr>';
        });
        tb.innerHTML = html;
        document.getElementById("approvalCount").textContent = orders.length;
        showToast(orders.length + " approval orders loaded", "success");
    } catch (error) {
        console.error("Refresh approval orders error:", error);
        tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#ea4335;padding:16px;">Error loading approval orders: ' + error.message + '</td></tr>';
        showToast("Error loading approval orders", "error");
    }
}

// ==============================================================
// COSTING APPROVAL MODAL
// ==============================================================

async function openCostingApprovalModal(orderId) {
    if (!orderId) {
        showToast("Order ID is required", "error");
        return;
    }
    showToast("Loading approval details...", "info");
    openModal("costingApprovalModal");

    document.getElementById("caFGContainer").innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fas fa-spinner fa-spin" style="font-size:24px;display:block;"></i> Loading...</div>';
    document.getElementById("caTotalCostSummary").innerHTML = "Total Cost: Loading...";

    try {
        const response = await fetch("/approval/order/" + orderId, {
            headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
        });
        if (!response.ok) throw new Error("Failed to load approval details");
        const data = await response.json();
        if (!data.success) {
            showToast(data.message || "Error loading order", "error");
            closeModal("costingApprovalModal");
            return;
        }
        document.getElementById("caOrderId").textContent = data.buyerOrderId || orderId;
        document.getElementById("caBuyerName").textContent = data.buyerName || data.fgs?.[0]?.buyerName || "Unknown";
        document.getElementById("caTotalFGs").textContent = data.totalFGs || 0;
        window._caOrderId = orderId;
        window._caFGData = data.fgs || [];
        renderCostingApprovalFGs(data.fgs || []);
        showToast("Approval details loaded", "success");
    } catch (error) {
        console.error("Costing Approval error:", error);
        document.getElementById("caFGContainer").innerHTML = '<div style="text-align:center;padding:30px;color:#ea4335;">Error: ' + error.message + '</div>';
        showToast("Error loading approval details", "error");
    }
}

function renderCostingApprovalFGs(fgs) {
    const container = document.getElementById("caFGContainer");
    if (!fgs || fgs.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">No FGs found</div>';
        return;
    }
    let html = "";
    let grandTotal = 0;
    fgs.forEach((fg, idx) => {
        const items = fg.bomItems || [];
        let fgTotal = 0;
        let rows = "";
        items.forEach((item, i) => {
            const cost = (item.consumption || 0) * (item.rate || 0);
            fgTotal += cost;
            rows += '<tr><td>' + (i + 1) + '</td><td>' + (item.item_no || "—") + '</td><td>' + (item.item_name || "—") + '</td><td>' + (item.item_size || "—") + '</td><td>' + (item.consumption || 0).toFixed(4) + '</td><td>' + (item.uom || "PCS") + '</td><td>₹' + (item.rate || 0).toFixed(2) + '</td><td style="font-weight:600;">₹' + cost.toFixed(2) + '</td></tr>';
        });
        grandTotal += fgTotal;
        html += '<div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;margin-bottom:12px;overflow:hidden;">';
        html += '<div style="background:var(--table-header);padding:8px 14px;display:flex;justify-content:space-between;border-bottom:1px solid var(--border-color);">';
        html += '<span style="font-weight:600;">FG ' + (idx + 1) + ': <span style="font-family:monospace;">' + (fg.fgKey || "—") + '</span></span>';
        html += '<span style="font-weight:600;color:#2a6df4;">₹' + fgTotal.toFixed(2) + '</span></div>';
        html += '<div style="padding:8px 12px;overflow-x:auto;"><table style="width:100%;font-size:12px;border-collapse:collapse;">';
        html += '<thead><tr style="background:var(--bg-input);"><th>#</th><th>Item No</th><th>Item Name</th><th>Size</th><th>Consumption</th><th>UOM</th><th>Rate</th><th>Cost</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
    });
    container.innerHTML = html;
    document.getElementById("caTotalCostSummary").innerHTML = 'Total Cost: <strong style="font-size:16px;">₹' + grandTotal.toFixed(2) + '</strong> <span style="font-size:12px;color:var(--text-muted);">(' + fgs.length + ' FG' + (fgs.length > 1 ? "s" : "") + ')</span>';
}

async function submitCostingDecision(decision) {
    const orderId = window._caOrderId;
    if (!orderId) { showToast("No order selected", "error"); return; }
    const reason = document.getElementById("caReason")?.value?.trim() || "";
    if (!confirm("Are you sure you want to " + (decision === "approve" ? "APPROVE" : "REJECT") + " costing for " + orderId + "?")) return;
    document.getElementById("caApproveBtn").disabled = true;
    document.getElementById("caRejectBtn").disabled = true;
    try {
        const endpoint = decision === "approve" ? "/approval/approve" : "/approval/reject";
        const payload = { buyer_order_id: orderId };
        if (decision === "reject") payload.rejection_reason = reason || "Rejected by approver";
        const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + localStorage.getItem("access_token") },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        document.getElementById("caApproveBtn").disabled = false;
        document.getElementById("caRejectBtn").disabled = false;
        if (result.success) {
            showToast(result.message, "success");
            closeModal("costingApprovalModal");
            refreshApprovalOrders();
            refreshBOMOrders();
            refreshRMOrders();
        } else {
            showToast("Error: " + result.message, "error");
        }
    } catch (error) {
        document.getElementById("caApproveBtn").disabled = false;
        document.getElementById("caRejectBtn").disabled = false;
        showToast("Error: " + error.message, "error");
    }
}

window.openCostingApprovalModal = openCostingApprovalModal;
window.renderCostingApprovalFGs = renderCostingApprovalFGs;
window.submitCostingDecision = submitCostingDecision;


// ==============================================================
// OUTWARD ORDERS - Placeholder
// ==============================================================

function openOutwardOrders() {
    showToast("Outward Orders module coming soon...", "info");
    console.log("Outward Orders - placeholder");
}

window.openOutwardOrders = openOutwardOrders;





function generatePOFromMaterials() {
    const data = window._rmOrderMaterials;
    const orderId = window._rmOrderId;
    if (!data || !orderId) {
        showToast("No materials to generate PO", "error");
        return;
    }
    showToast("Generating PO...", "info");
    const supplier = data.supplier || "Unknown";
    const items = data.items || [];
    if (items.length === 0) {
        showToast("No items to order", "error");
        return;
    }
    const poData = {
        supplier: supplier,
        supplier_alias: supplier,
        selected_items: items.map(item => ({
            fgKey: item.fgKey || orderId,
            itemNo: item.itemNo || "",
            itemName: item.itemName || "",
            garmentSize: item.garmentSize || "ALL",
            color: item.color || "",
            itemSize: item.itemSize || "",
            requiredQty: item.requiredQty || 0,
            balanceToOrder: item.requiredQty || 0,
            uom: item.uom || "PCS",
            rate: item.rate || 0,
            cgst: item.cgst || 0,
            igst: item.igst || 0,
            hsn: item.hsn || "",
            requirementKey: item.requirementKey || "",
            buyerOrderNo: data.buyerOrderNo || "",
                buyerOrderId: orderId,
            orderDate: data.orderDate || null,
            consumption: item.consumption || 1,
            leadtime: item.leadtime || 0
        })),
        excess_percentage: 0,
        cgst_override: {},
        sgst_override: {},
        igst_override: {},
        allow_extra: false
    };
    fetch("/rm-order/generate-po", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + localStorage.getItem("access_token")
        },
        body: JSON.stringify(poData)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            showToast("PO generated successfully", "success");
            document.getElementById("rmProcessModal").remove();
            if (result.poHTML) {
            }
            refreshRMOrders();
        } else {
            showToast("Error: " + result.message, "error");
        }
    })
    .catch(e => showToast("Error: " + e.message, "error"));
}
window.generatePOFromMaterials = generatePOFromMaterials;
window.generatePOFromMaterials = generatePOFromMaterials;
window.viewRMMaterials = viewRMMaterials;








async function viewRMMaterials(orderId) {
    showToast("Loading materials for " + orderId + "...", "info");
    try {
        // Fetch inventory items
        var invResponse = await fetch("/master/inventory/", {
            headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
        });
        var inventoryItems = await invResponse.json();
        window._inventoryItems = inventoryItems || [];
        // Build lookup maps
        var invMap = {};
        inventoryItems.forEach(function(item) {
            var key = item.item_no || item.id || "";
            if (key) invMap[key] = item;
            // Also map by name
            if (item.item_name) invMap[item.item_name] = item;
        });
        window._invMap = invMap;

        const response = await fetch("/rm-order/materials/" + orderId, {
            headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
        });
        const data = await response.json();
        if (!data.success) {
            showToast("Error: " + data.message, "error");
            return;
        }

        // Filter out suppliers who already have a live PO for this buyer order.
        // A "live PO" means any non-CANCELLED RM_ORDER row for this buyer order
        // whose extra_data.supplier matches. Those suppliers have already been
        // ordered and must not appear in the process modal again.
        try {
            const rmOrdersResp = await fetch("/rm-order/materials/" + orderId, {
                headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
            });
            // No separate endpoint for "ordered suppliers" — derive it from the
            // RM Order table response instead.
            const rmTableResp = await fetch("/rm-order/orders", {
                headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
            });
            const rmTable = await rmTableResp.json();
            const thisOrder = (rmTable || []).find(function(o) { return o.buyerOrderId === orderId; });
            // We don't have per-supplier info in the table row. Fall back to
            // querying the GRN-tab PO list which exposes per-supplier POs.
            const poListResp = await fetch("/grn/orders?buyer_order_id=" + encodeURIComponent(orderId), {
                headers: { "Authorization": "Bearer " + localStorage.getItem("access_token") }
            });
            const poList = await poListResp.json();
            const orderedSuppliers = new Set();
            (poList || []).forEach(function(po) {
                const sup = po.supplierAlias || po.supplier;
                if (sup) orderedSuppliers.add(sup);
            });
            if (orderedSuppliers.size > 0) {
                data.supplierGroups = (data.supplierGroups || []).filter(function(g) {
                    return !orderedSuppliers.has(g.supplier);
                });
            }
        } catch (e) {
            console.warn("Could not filter ordered suppliers:", e);
        }

        window._rmOrderMaterials = data;
        window._rmOrderId = orderId;
        const existing = document.getElementById("rmProcessModal");
        if (existing) existing.remove();
        
        // FULL PAGE MODAL
        let html = '<div class="modal" id="rmProcessModal" style="display:flex;">';
        html += '<div class="modal-box full" style="display:flex;flex-direction:column;padding:0;">';
        html += '<div style="position:sticky;top:0;background:var(--bg-card);padding:12px 20px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:center;z-index:10;flex-wrap:wrap;gap:8px;">';
        html += '<h2 style="margin:0;"><i class="fas fa-boxes" style="color:#2a6df4;"></i> RM Materials - ' + orderId + '</h2>';
        html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
        html += '<button class="btn btn-info btn-sm" onclick="printRMOrderMaterials()"><i class="fas fa-print"></i> Print</button>';
        html += '<button class="btn btn-outline btn-sm" onclick="document.getElementById(\'rmProcessModal\').remove()">Close</button>';
        html += '</div></div>';
        html += '<div style="flex:1;overflow-y:auto;padding:20px 24px;background:var(--bg-primary);">';
        html += '<p class="text-muted">Buyer: ' + (data.buyerName || "N/A") + ' | Order No: ' + (data.buyerOrderNo || "N/A") + '</p>';
        
        var groups = data.supplierGroups || [];
        if (groups.length === 0) {
            html += '<div class="text-muted" style="padding:20px;text-align:center;">No materials found</div>';
        } else {
            groups.forEach(function(group, gIdx) {
                html += '<div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;margin-bottom:16px;overflow:hidden;">';
                html += '<div style="background:var(--table-header);padding:10px 16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--border-color);">';
                html += '<strong style="color:var(--nav-active-text);">Supplier: ' + (group.supplier || "Unknown") + '</strong>';
                html += '<span style="font-size:12px;color:var(--text-muted);">Total Qty: ' + (group.totalQty || 0).toFixed(2) + ' | Amount: ₹' + (group.totalAmount || 0).toFixed(2) + '</span>';
                html += '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">';
                html += '<label style="font-size:11px;color:var(--text-muted);">Apply to all:</label>';
                html += '<input type="number" step="0.1" placeholder="CGST%" style="width:60px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;" oninput="applyCommonTax(' + gIdx + ', \'cgst\', this.value)">';
                html += '<input type="number" step="0.1" placeholder="SGST%" style="width:60px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;" oninput="applyCommonTax(' + gIdx + ', \'sgst\', this.value)">';
                html += '<input type="number" step="0.1" placeholder="IGST%" style="width:60px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;" oninput="applyCommonTax(' + gIdx + ', \'igst\', this.value)">';
                html += '<button class="btn btn-success btn-sm" onclick="generatePOForSupplier(\'' + orderId + '\', \'' + group.supplier + '\')"><i class="fas fa-file-pdf"></i> Generate PO</button>';
                html += '</div>';
                html += '</div>';
                html += '<div style="padding:12px;overflow-x:auto;">';
                html += '<table style="width:100%;font-size:12px;border-collapse:collapse;">';
                html += '<thead><tr style="background:var(--bg-input);">';
                html += '<th style="padding:6px 8px;text-align:left;">Item No</th>';
                html += '<th style="padding:6px 8px;text-align:left;">Item Name</th>';
                html += '<th style="padding:6px 8px;text-align:left;">FG Size</th>';
                html += '<th style="padding:6px 8px;text-align:left;">RM Size</th>';
                html += '<th style="padding:6px 8px;text-align:left;">RM Color</th>';
                html += '<th style="padding:6px 8px;text-align:left;">HSN</th>';
                html += '<th style="padding:6px 8px;text-align:center;">Qty</th>';
                html += '<th style="padding:6px 8px;text-align:center;">UOM</th>';
                html += '<th style="padding:6px 8px;text-align:right;">Rate</th>';
                html += '<th style="padding:6px 8px;text-align:right;">Amount</th>';
                html += '<th style="padding:6px 8px;text-align:center;">CGST%</th>';
                html += '<th style="padding:6px 8px;text-align:center;">SGST%</th>';
                html += '<th style="padding:6px 8px;text-align:center;">IGST%</th>';
                html += '</tr></thead><tbody>';
                (group.items || []).forEach(function(item, idx) {
                    var amount = (item.rate || 0) * (item.requiredQty || 0);
                    var cgst = item.cgst || 0;
                    var igst = item.igst || 0;
                    // Look up inventory item for RM Size and Color
                    var invItem = window._invMap[item.itemNo] || {};
                    // Prefer the payload value (it is what the PO will aggregate on).
                    var rmSize = (item.itemSize || invItem.size || invItem.extra_data?.size || "");
                    // RM colour comes from the payload or the RM item only. Never
                    // the garment colour — that varied per FG and blocked
                    // aggregation across FGs on the same RM item.
                    var rmColor = (item.color || invItem.color || invItem.extra_data?.color || "");
                    html += '<tr data-supplier="' + (group.supplier || '').replace(/"/g, '&quot;') + '" data-group-idx="' + gIdx + '" data-row-idx="' + idx + '">';
                    html += '<td style="padding:4px 6px;">' + (item.itemNo || "—") + '</td>';
                    html += '<td style="padding:4px 6px;">' + (item.itemName || "—") + '</td>';
                    html += '<td style="padding:4px 6px;">' + (item.garmentSize || "ALL") + '</td>';
                    html += '<td style="padding:4px 6px;"><input type="text" class="rm-size-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + rmSize + '" list="rmSizeDatalist" style="width:70px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    html += '<td style="padding:4px 6px;"><input type="text" class="rm-color-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + rmColor + '" list="rmColorDatalist" style="width:70px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    html += '<td style="padding:4px 6px;"><input type="text" class="rm-hsn-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + (item.hsn || invItem.hsn || "") + '" style="width:60px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    html += '<td style="padding:4px 6px;text-align:center;">' + (item.requiredQty || 0).toFixed(2) + '</td>';
                    html += '<td style="padding:4px 6px;text-align:center;">' + (item.uom || "PCS") + '</td>';
                    html += '<td style="padding:4px 6px;text-align:right;">₹' + (item.rate || 0).toFixed(2) + '</td>';
                    html += '<td style="padding:4px 6px;text-align:right;">₹' + amount.toFixed(2) + '</td>';
                    html += '<td style="padding:4px 6px;text-align:center;"><input type="number" class="rm-cgst-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + cgst + '" step="0.1" style="width:45px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    var sgst = item.sgst || 0;
                    html += '<td style="padding:4px 6px;text-align:center;"><input type="number" class="rm-sgst-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + sgst + '" step="0.1" style="width:45px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    html += '<td style="padding:4px 6px;text-align:center;"><input type="number" class="rm-igst-input" data-group="' + gIdx + '" data-idx="' + idx + '" value="' + igst + '" step="0.1" style="width:45px;padding:2px 4px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;"></td>';
                    html += '</tr>';
                });
                html += '</tbody></table></div></div>';
            });
        }
        html += '</div></div></div>';
        var div = document.createElement("div");
        div.innerHTML = html;
        document.body.appendChild(div.firstElementChild);
        document.getElementById("rmProcessModal").classList.add("active");
        setupRMAutocomplete();
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

function applyCommonTax(groupIdx, field, value) {
    // Write the given tax % to every row of this supplier group that the user
    // has not manually touched. Rows the user edits later keep their own value.
    var v = parseFloat(value);
    if (isNaN(v)) return;
    var selectorMap = { cgst: '.rm-cgst-input', sgst: '.rm-sgst-input', igst: '.rm-igst-input' };
    var sel = selectorMap[field];
    if (!sel) return;
    var rows = document.querySelectorAll('#rmProcessModal tr[data-group-idx="' + groupIdx + '"]');
    rows.forEach(function(row) {
        var input = row.querySelector(sel);
        if (!input) return;
        if (input.dataset.userTouched === '1') return;
        input.value = v;
    });
}

// Mark a tax input as user-touched so common-tax writes skip it
document.addEventListener('input', function(e) {
    if (e.target && (e.target.classList.contains('rm-cgst-input') ||
                     e.target.classList.contains('rm-sgst-input') ||
                     e.target.classList.contains('rm-igst-input'))) {
        e.target.dataset.userTouched = '1';
    }
});

function setupRMAutocomplete() {
    var items = window._inventoryItems || [];
    var sizeDatalist = document.getElementById("rmSizeDatalist");
    if (!sizeDatalist) {
        sizeDatalist = document.createElement("datalist");
        sizeDatalist.id = "rmSizeDatalist";
        document.body.appendChild(sizeDatalist);
    }
    sizeDatalist.innerHTML = "";
    var sizes = new Set();
    items.forEach(function(item) {
        if (item.size) sizes.add(item.size);
        if (item.extra_data && item.extra_data.size) sizes.add(item.extra_data.size);
    });
    sizes.forEach(function(s) { if (s) { var opt = document.createElement("option"); opt.value = s; sizeDatalist.appendChild(opt); } });
    
    var colorDatalist = document.getElementById("rmColorDatalist");
    if (!colorDatalist) {
        colorDatalist = document.createElement("datalist");
        colorDatalist.id = "rmColorDatalist";
        document.body.appendChild(colorDatalist);
    }
    colorDatalist.innerHTML = "";
    var colors = new Set();
    items.forEach(function(item) {
        if (item.color) colors.add(item.color);
        if (item.extra_data && item.extra_data.color) colors.add(item.extra_data.color);
    });
    colors.forEach(function(c) { if (c) { var opt = document.createElement("option"); opt.value = c; colorDatalist.appendChild(opt); } });
}
window.viewRMMaterials = viewRMMaterials;
window.setupRMAutocomplete = setupRMAutocomplete;

// ==============================================================
// GENERATE PO FOR SUPPLIER
// ==============================================================

async function generatePOForSupplier(orderId, supplier) {
    if (!supplier || supplier === "Unknown") {
        showToast("No supplier selected", "error");
        return;
    }
    const data = window._rmOrderMaterials;
    if (!data) {
        showToast("No materials data found", "error");
        return;
    }
    // Find the supplier group
    var groups = data.supplierGroups || [];
    var group = null;
    for (var i = 0; i < groups.length; i++) {
        if (groups[i].supplier === supplier) {
            group = groups[i];
            break;
        }
    }
    if (!group || !group.items || group.items.length === 0) {
        showToast("No items found for supplier: " + supplier, "error");
        return;
    }
    // Read user-edited values from modal - FILTER by supplier
    var items = [];
    var allRows = document.querySelectorAll('#rmProcessModal tbody tr');
    var rows = [];
    for (var i2 = 0; i2 < allRows.length; i2++) {
        if (allRows[i2].dataset.supplier === supplier) {
            rows.push(allRows[i2]);
        }
    }
    for (var r = 0; r < rows.length; r++) {
        var row = rows[r];
        var rowIdx = parseInt(row.dataset.rowIdx) || 0;
        var rmSizeInput = row.querySelector('.rm-size-input');
        var rmColorInput = row.querySelector('.rm-color-input');
        var hsnInput = row.querySelector('.rm-hsn-input');
        var cgstInput = row.querySelector('.rm-cgst-input');
        var sgstInput = row.querySelector('.rm-sgst-input');
        var igstInput = row.querySelector('.rm-igst-input');
        if (rmSizeInput) {
            var originalItem = group.items[rowIdx] || {};
            var cgst = parseFloat(cgstInput.value) || 0;
            var sgst = parseFloat(sgstInput.value) || 0;
            var igst = parseFloat(igstInput.value) || 0;
            // Intra-state (CGST+SGST) vs inter-state (IGST). Both halves must
            // survive into the payload; do not collapse to cgst-only.
            var finalCgst = cgst;
            var finalSgst = sgst;
            var finalIgst = igst;
            items.push({
                fgKey: orderId,
                itemNo: originalItem.itemNo || "",
                itemName: originalItem.itemName || "",
                garmentSize: originalItem.garmentSize || "ALL",
                color: rmColorInput.value || "",
                itemSize: rmSizeInput.value || originalItem.itemSize || "",
                requiredQty: originalItem.requiredQty || 0,
                balanceToOrder: originalItem.requiredQty || 0,
                uom: originalItem.uom || "PCS",
                rate: originalItem.rate || 0,
                cgst: finalCgst,
                sgst: finalSgst,
                igst: finalIgst,
                hsn: hsnInput.value || originalItem.hsn || "",
                requirementKey: originalItem.requirementKey || "",
                buyerOrderNo: data.buyerOrderNo || "",
                buyerOrderId: orderId,
                orderDate: data.orderDate || null,
                consumption: originalItem.consumption || 1,
                leadtime: originalItem.leadtime || 0
            });
        }
    }
    if (items.length === 0) {
        showToast("No valid items found", "error");
        return;
    }
    var excess = parseFloat(prompt("Enter excess percentage (0-5%):", "0")) || 0;
    if (excess > 5) { showToast("Excess cannot exceed 5%", "error"); return; }
    showToast("Generating PO for " + supplier + "...", "info");
    var poData = {
        supplier: supplier,
        supplier_alias: supplier,
        selected_items: items,
        excess_percentage: excess,
        cgst_override: {},
        sgst_override: {},
        igst_override: {},
        allow_extra: excess > 0
    };
    try {
        var response = await fetch("/rm-order/generate-po", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + localStorage.getItem("access_token")
            },
            body: JSON.stringify(poData)
        });
        var result = await response.json();
        if (result.success) {
            showToast("PO generated: " + result.poToken, "success");
            document.getElementById("rmProcessModal").remove();
            var processResp = await fetch("/rm-order/process", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + localStorage.getItem("access_token")
                },
                body: JSON.stringify({ po_token: result.poToken })
            });
            var processResult = await processResp.json();
            if (processResult.success) {
                showToast("PO sent to GRN", "success");
                refreshRMOrders();
                refreshGRNOrders();
            } else {
                showToast("PO created but process failed: " + processResult.message, "warning");
            }
            if (result.poHTML) {
            }
        } else {
            showToast("Error: " + result.message, "error");
        }
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

window.generatePOForSupplier = generatePOForSupplier;




window.printRMOrderMaterials = printRMOrderMaterials;

// ==============================================================
// CANCEL RM ORDER FROM CARD
// ==============================================================

async function cancelRMOrderFromCard(buyerOrderId) {
    if (!buyerOrderId) {
        showToast("No order ID found", "error");
        return;
    }
    if (!confirm("⚠️ Are you sure you want to cancel RM Order for " + buyerOrderId + "?\nThis will move the order back to Costing Approval.")) {
        return;
    }
    var confirmText = prompt('Type "CANCEL" to confirm cancellation:');
    if (confirmText !== "CANCEL") {
        showToast("Cancellation aborted", "info");
        return;
    }
    showToast("Cancelling RM Order...", "info");
    try {
        var r = await API.call('/rm-order/cancel-buyer-order', 'POST', { buyer_order_id: buyerOrderId });
        if (r.success) {
            showToast(r.message || "RM Order cancelled successfully", "success");
            refreshRMOrders();
            refreshApprovalOrders();
            refreshBuyerOrders();
        } else {
            showToast("Error: " + r.message, "error");
        }
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

window.cancelRMOrderFromCard = cancelRMOrderFromCard;


function printRMOrderMaterials() {
    var data = window._rmOrderMaterials;
    if (!data) {
        showToast("No data to print", "error");
        return;
    }
    var win = window.open("", "_blank");
    if (!win) {
        showToast("Please allow popups", "error");
        return;
    }
    var html = "<html><head><title>RM Materials - " + (data.buyerOrderId || "") + "</title><style>";
    html += "body { font-family: Arial, sans-serif; padding: 20px; font-size: 11px; }";
    html += "table { width: 100%; border-collapse: collapse; margin-top: 10px; }";
    html += "th { background: #1a3a6a; color: white; padding: 6px 8px; text-align: left; border: 1px solid #333; }";
    html += "td { padding: 4px 6px; border: 1px solid #ccc; }";
    html += ".header { text-align: center; border-bottom: 2px solid #2a6df4; padding-bottom: 10px; margin-bottom: 15px; }";
    html += ".header h2 { color: #1a3a6a; margin: 0; }";
    html += ".supplier-group { margin-top: 15px; border: 1px solid #ddd; border-radius: 4px; overflow: hidden; }";
    html += ".supplier-header { background: #f0f4fe; padding: 8px 12px; font-weight: bold; border-bottom: 1px solid #ddd; }";
    html += ".totals { margin-top: 10px; font-weight: bold; text-align: right; }";
    html += "@media print { .no-print { display: none; } }";
    html += "</style></head><body>";
    html += '<div class="header"><h2>Sneha Creations - RM Materials</h2>';
    html += "<p><strong>Buyer Order:</strong> " + (data.buyerOrderId || "N/A") + " | <strong>Buyer:</strong> " + (data.buyerName || "N/A") + " | <strong>Order No:</strong> " + (data.buyerOrderNo || "N/A") + "</p></div>";
    var groups = data.supplierGroups || [];
    if (groups.length === 0) {
        html += "<p>No materials found.</p>";
    } else {
        groups.forEach(function(group) {
            html += '<div class="supplier-group">';
            html += '<div class="supplier-header">Supplier: ' + (group.supplier || "Unknown") + ' | Total Qty: ' + (group.totalQty || 0).toFixed(2) + ' | Amount: ₹' + (group.totalAmount || 0).toFixed(2) + '</div>';
            html += '<table><thead><tr><th>#</th><th>Item No</th><th>Item Name</th><th>FG Size</th><th>RM Size</th><th>RM Color</th><th>HSN</th><th>Qty</th><th>UOM</th><th>Rate</th><th>Amount</th><th>CGST%</th><th>SGST%</th><th>IGST%</th></tr></thead><tbody>';
            (group.items || []).forEach(function(item, idx) {
                var amount = (item.rate || 0) * (item.requiredQty || 0);
                var cgst = item.cgst || 0;
                var igst = item.igst || 0;
                html += "<tr><td>" + (idx + 1) + "</td><td>" + (item.itemNo || "—") + "</td><td>" + (item.itemName || "—") + "</td><td>" + (item.garmentSize || "ALL") + "</td><td>" + (item.itemSize || "—") + "</td><td>" + (item.color || "—") + "</td><td>" + (item.hsn || "—") + "</td><td>" + (item.requiredQty || 0).toFixed(2) + "</td><td>" + (item.uom || "PCS") + "</td><td>₹" + (item.rate || 0).toFixed(2) + "</td><td>₹" + amount.toFixed(2) + "</td><td>" + (cgst > 0 ? cgst + "%" : "—") + "</td><td>" + (cgst > 0 ? cgst + "%" : "—") + "</td><td>" + (igst > 0 ? igst + "%" : "—") + "</td></tr>";
            });
            html += "</tbody></table></div>";
        });
    }
    html += '<div class="no-print" style="margin-top:20px;text-align:center;"><button onclick="window.print()" style="padding:8px 20px;background:#2a6df4;color:white;border:none;border-radius:4px;cursor:pointer;">Print</button></div>';
    html += '<p style="margin-top:20px;text-align:center;font-size:10px;color:#666;">Generated on ' + new Date().toLocaleString() + '</p>';
    html += "</body></html>";
    win.document.write(html);
    win.document.close();
    win.focus();
}

window.printRMOrderMaterials = printRMOrderMaterials;


// ==============================================================
// GENERATE ALL POS - Universal PO generation
// ==============================================================

async function generateAllPOs() {
    const data = window._rmOrderMaterials;
    if (!data) {
        showToast("No materials data found", "error");
        return;
    }
    var groups = data.supplierGroups || [];
    if (groups.length === 0) {
        showToast("No suppliers found", "error");
        return;
    }
    var excess = parseFloat(prompt("Enter excess percentage (0-5%):", "0")) || 0;
    if (excess > 5) { showToast("Excess cannot exceed 5%", "error"); return; }
    showToast("Generating POs for all suppliers...", "info");
    
    var totalGenerated = 0;
    var totalFailed = 0;
    var orderId = window._rmOrderId;
    
    // Get all rows from the modal, grouped by supplier via data-supplier attribute
    var allRows = document.querySelectorAll('#rmProcessModal tbody tr');
    
    for (var i = 0; i < groups.length; i++) {
        var group = groups[i];
        var supplier = group.supplier;
        if (!supplier || supplier === "Unknown") continue;
        
        // Filter DOM rows belonging to THIS supplier
        var supplierRows = [];
        for (var r = 0; r < allRows.length; r++) {
            if (allRows[r].dataset.supplier === supplier) {
                supplierRows.push(allRows[r]);
            }
        }
        
        if (supplierRows.length === 0) continue;
        
        // Build item list from supplier's rows (already ordered correctly in DOM)
        var items = [];
        for (var r2 = 0; r2 < supplierRows.length; r2++) {
            var row = supplierRows[r2];
            var rowIdx = parseInt(row.dataset.rowIdx) || 0;
            var originalItem = (group.items && group.items[rowIdx]) || {};
            var rmSizeInput = row.querySelector('.rm-size-input');
            var rmColorInput = row.querySelector('.rm-color-input');
            var hsnInput = row.querySelector('.rm-hsn-input');
            var cgstInput = row.querySelector('.rm-cgst-input');
            var sgstInput = row.querySelector('.rm-sgst-input');
            var igstInput = row.querySelector('.rm-igst-input');
            if (!rmSizeInput) continue;
            var cgst = parseFloat(cgstInput.value) || 0;
            var sgst = parseFloat(sgstInput.value) || 0;
            var igst = parseFloat(igstInput.value) || 0;
            // Intra-state (CGST+SGST) vs inter-state (IGST). Both halves must
            // survive into the payload; do not collapse to cgst-only.
            var finalCgst = cgst;
            var finalSgst = sgst;
            var finalIgst = igst;
            items.push({
                fgKey: orderId,
                itemNo: originalItem.itemNo || "",
                itemName: originalItem.itemName || "",
                garmentSize: originalItem.garmentSize || "ALL",
                color: rmColorInput.value || "",
                itemSize: rmSizeInput.value || originalItem.itemSize || "",
                requiredQty: originalItem.requiredQty || 0,
                balanceToOrder: originalItem.requiredQty || 0,
                uom: originalItem.uom || "PCS",
                rate: originalItem.rate || 0,
                cgst: finalCgst,
                sgst: finalSgst,
                igst: finalIgst,
                hsn: hsnInput.value || originalItem.hsn || "",
                requirementKey: originalItem.requirementKey || "",
                buyerOrderNo: data.buyerOrderNo || "",
                buyerOrderId: orderId,
                orderDate: data.orderDate || null,
                consumption: originalItem.consumption || 1,
                leadtime: originalItem.leadtime || 0
            });
        }
        if (items.length === 0) continue;
        
        var poData = {
            supplier: supplier,
            supplier_alias: supplier,
            selected_items: items,
            excess_percentage: excess,
            cgst_override: {},
            sgst_override: {},
            igst_override: {},
            allow_extra: excess > 0
        };
        
        try {
            var response = await fetch("/rm-order/generate-po", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + localStorage.getItem("access_token")
                },
                body: JSON.stringify(poData)
            });
            var result = await response.json();
            if (result.success) {
                totalGenerated++;
                // Auto-process each PO
                var processResp = await fetch("/rm-order/process", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + localStorage.getItem("access_token")
                    },
                    body: JSON.stringify({ po_token: result.poToken })
                });
                var processResult = await processResp.json();
                if (!processResult || !processResult.success) {
                    console.warn("PO " + result.poToken + " created but process failed: " + (processResult ? processResult.message : 'null response'));
                }
            } else {
                totalFailed++;
                console.error("Failed for supplier: " + supplier, result.message);
            }
        } catch (e) {
            totalFailed++;
            console.error("Error for supplier: " + supplier, e.message);
        }
    }
    
    if (totalGenerated > 0) {
        showToast("Generated " + totalGenerated + " PO(s)" + (totalFailed > 0 ? ", " + totalFailed + " failed" : ""), totalFailed > 0 ? "warning" : "success");
        document.getElementById("rmProcessModal").remove();
        refreshRMOrders();
        refreshRMInspection();
        refreshGRNOrders();
    } else {
        showToast("No POs generated. Check console for errors.", "error");
    }
}

window.generateAllPOs = generateAllPOs;

