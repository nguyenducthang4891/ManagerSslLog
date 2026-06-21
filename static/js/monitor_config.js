/**
 * monitoring_config.js
 * Logic riêng cho trang monitor/config_list.html (CRUD ELKClusterConfig +
 * AlertThreshold). Dùng chung postAndReload()/fetchJSON()/toggleModal() từ
 * common.js -- base.html đã load common.js trước file này.
 */

// ============================================================================
// ELKClusterConfig
// ============================================================================

/** Hiện/ẩn ô chọn Tenant trong modal Thêm cụm ELK dựa theo "Phạm vi" đã chọn. */
function onIsDefaultChange() {
    const isDefault = document.getElementById('selectIsDefault').value === 'true';
    const tenantGroup = document.getElementById('groupTenantSelect');
    tenantGroup.classList.toggle('d-none', isDefault);
}

/** Submit form Thêm cụm ELK. */
function submitAddElkConfig(event) {
    const form = document.getElementById('formAddElkConfig');
    const formData = new FormData(form);

    postAndReload('/monitor/api/elk-config/add/', formData, {event}).then(result => {
        if (result.ok) {
            toggleModal('modalAddElkConfig', false);
        }
    });
}

/** Mở modal Sửa cụm ELK, điền sẵn dữ liệu hiện tại vào form. */
function openEditElkConfigModal(configId, name, hosts, username) {
    document.getElementById('editElkConfigId').value = configId;
    document.getElementById('editElkName').value = name;
    document.getElementById('editElkHosts').value = hosts;
    document.getElementById('editElkUsername').value = username;
    toggleModal('modalEditElkConfig', true);
}

/** Submit form Sửa cụm ELK. */
function submitEditElkConfig(event) {
    const form = document.getElementById('formEditElkConfig');
    const formData = new FormData(form);
    const configId = document.getElementById('editElkConfigId').value;

    postAndReload(`/monitor/api/elk-config/${configId}/edit/`, formData, {event}).then(result => {
        if (result.ok) {
            toggleModal('modalEditElkConfig', false);
        }
    });
}

/** Xóa cụm ELK, có xác nhận trước khi xóa. */
function deleteElkConfig(configId, name) {
    postAndReload(`/monitor/api/elk-config/${configId}/delete/`, null, {
        confirmMessage: `Xóa cấu hình cụm ELK "${name}"? Hành động này không thể hoàn tác.`,
    });
}

// ============================================================================
// AlertThreshold
// ============================================================================

/** Submit form Thêm/Cập nhật ngưỡng cảnh báo. */
function submitUpsertThreshold(event) {
    const form = document.getElementById('formUpsertThreshold');
    const formData = new FormData(form);

    postAndReload('/monitor/api/threshold/upsert/', formData, {event}).then(result => {
        if (result.ok) {
            toggleModal('modalUpsertThreshold', false);
        }
    });
}

/** Xóa ngưỡng tùy biến, có xác nhận trước khi xóa. */
function deleteThreshold(thresholdId, metricLabel) {
    postAndReload(`/monitor/api/threshold/${thresholdId}/delete/`, null, {
        confirmMessage: `Xóa ngưỡng cảnh báo cho "${metricLabel}"? Hệ thống sẽ dùng lại ngưỡng mặc định.`,
    });
}