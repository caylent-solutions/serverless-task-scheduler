import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { API_BASE_URL } from '../../config';


export default function TenantSelector({ onSetTenant }) {

  const [ tenants, setTenants ] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/tenants`)
      .then(response => response.json())
      // Using Set to remove duplicates, then convert back to array using spread operator
      .then(data => [...new Set((data ?? []).map(tenant => tenant.tenant_id))])
      .then(data => setTenants(data))
      .catch(error => console.error('Error fetching tenants:', error));
  }, []);

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-8 shadow-sm">
      <h1 className="text-gray-800 text-2xl font-semibold mb-6">Select your tenant</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {tenants.map(tenant => (
          <div key={tenant} className="bg-gray-50 border border-gray-200 rounded-lg p-4 hover:bg-gray-100 transition-colors">
            <div className="flex items-center justify-between">
              <span className="text-gray-800 font-medium">{tenant}</span>
              <button 
                onClick={() => onSetTenant(tenant)}
                className="bg-blue-500 text-white border-none rounded-md px-4 py-2 text-sm font-medium cursor-pointer transition-colors hover:bg-blue-600"
              >
                Select
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

TenantSelector.propTypes = {
  onSetTenant: PropTypes.func.isRequired
};