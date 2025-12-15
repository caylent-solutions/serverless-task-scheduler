import { useState } from 'react';
import PropTypes from 'prop-types';
import authenticatedFetch from '../../utils/api';

export default function ScheduleDialog({ 
    isOpen, 
    onClose, 
    targetAlias, 
    tenantName, 
    onScheduleCreated,
    exampleJson
}) {
    const [scheduleForm, setScheduleForm] = useState({
        schedule_expression: 'rate(1 hour)',
        target_input: exampleJson ? JSON.parse(exampleJson) : {},
        description: '',
        timezone: 'UTC',
        start_date: '',
        end_date: '',
        state: 'ENABLED'
    });
    const [targetInputText, setTargetInputText] = useState(exampleJson ? JSON.stringify(exampleJson, null, 2) : '{}');
    const [scheduleLoading, setScheduleLoading] = useState(false);

    const handleScheduleFormChange = (field, value) => {
        setScheduleForm(prev => ({
            ...prev,
            [field]: value
        }));
    };

    const handleCreateSchedule = async (e) => {
        e.preventDefault();
        setScheduleLoading(true);
        
        try {
            // Parse the target_input JSON
            let parsedTargetInput = {};
            try {
                parsedTargetInput = JSON.parse(targetInputText);
            } catch (parseError) {
                console.error('JSON parse error in target input:', parseError);
                alert('Invalid JSON in Target Input field. Please check your JSON syntax.');
                setScheduleLoading(false);
                return;
            }

            const formData = {
                ...scheduleForm,
                target_input: parsedTargetInput
            };

            const response = await authenticatedFetch(`./tenants/${tenantName}/targets/${targetAlias}/schedules`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            if (!response.ok) {
                throw new Error('Failed to create schedule');
            }

            const result = await response.json();
            alert('Schedule created successfully!');
            
            // Reset form
            setScheduleForm({
                schedule_expression: 'rate(1 hour)',
                target_input: exampleJson ? JSON.parse(exampleJson) : {},
                description: '',
                timezone: 'UTC',
                start_date: '',
                end_date: '',
                state: 'ENABLED'
            });
            setTargetInputText(exampleJson ? JSON.stringify(exampleJson, null, 2) : '{}');
            
            // Close dialog and notify parent
            onClose();
            if (onScheduleCreated) {
                onScheduleCreated(result);
            }
        } catch (error) {
            console.error('Error creating schedule:', error);
            alert('Error creating schedule');
        } finally {
            setScheduleLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-semibold text-gray-800">Create Schedule for {targetAlias}</h3>
                    <button
                        onClick={onClose}
                        className="text-gray-500 hover:text-gray-700"
                    >
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <form onSubmit={handleCreateSchedule} className="space-y-4">
                    {/* Tenant */}
                    <div>
                        <label htmlFor="schedule-tenant" className="block text-sm font-medium text-gray-700 mb-2">
                            Tenant
                        </label>
                        <input
                            id="schedule-tenant"
                            type="text"
                            value={tenantName}
                            readOnly
                            disabled
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 bg-gray-100 cursor-not-allowed"
                        />
                    </div>

                    {/* Schedule Expression */}
                    <div>
                        <div className="flex justify-between items-center mb-2">
                            <label htmlFor="schedule-expression" className="block text-sm font-medium text-gray-700">
                                Schedule Expression *
                            </label>
                            <a
                                href="https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-scheduled-rule-pattern.html"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-600 hover:text-blue-800 hover:underline"
                            >
                                Help
                            </a>
                        </div>
                        <input
                            id="schedule-expression"
                            type="text"
                            value={scheduleForm.schedule_expression}
                            onChange={(e) => handleScheduleFormChange('schedule_expression', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500 font-mono text-sm"
                            placeholder="e.g., rate(1 hour), cron(0 9 * * ? *)"
                            required
                        />
                        <p className="text-xs text-gray-500 mt-1">
                            Use rate() for intervals or cron() for specific times
                        </p>
                    </div>

                    {/* Target Input */}
                    <div>
                        <label htmlFor="schedule-target-input" className="block text-sm font-medium text-gray-700 mb-2">
                            Target Input (JSON) *
                        </label>
                        <textarea
                            id="schedule-target-input"
                            value={targetInputText}
                            onChange={(e) => setTargetInputText(e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500 font-mono text-sm"
                            rows={4}
                            placeholder={exampleJson ? JSON.stringify(exampleJson, null, 2) : '{"key": "value"}'}
                            required
                        />
                        <p className="text-xs text-gray-500 mt-1">
                            Enter valid JSON that will be passed to the function when the schedule triggers
                        </p>
                    </div>

                    {/* Description */}
                    <div>
                        <label htmlFor="schedule-description" className="block text-sm font-medium text-gray-700 mb-2">
                            Description
                        </label>
                        <input
                            id="schedule-description"
                            type="text"
                            value={scheduleForm.description}
                            onChange={(e) => handleScheduleFormChange('description', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500"
                            placeholder="Optional description for this schedule"
                        />
                    </div>

                    {/* Timezone */}
                    <div>
                        <label htmlFor="schedule-timezone" className="block text-sm font-medium text-gray-700 mb-2">
                            Timezone
                        </label>
                        <select
                            id="schedule-timezone"
                            value={scheduleForm.timezone}
                            onChange={(e) => handleScheduleFormChange('timezone', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500"
                        >
                            <option value="UTC">UTC</option>
                            <option value="America/New_York">America/New_York</option>
                            <option value="America/Los_Angeles">America/Los_Angeles</option>
                            <option value="Europe/London">Europe/London</option>
                            <option value="Europe/Paris">Europe/Paris</option>
                            <option value="Asia/Tokyo">Asia/Tokyo</option>
                        </select>
                    </div>

                    {/* Start Date */}
                    <div>
                        <label htmlFor="schedule-start-date" className="block text-sm font-medium text-gray-700 mb-2">
                            Start Date
                        </label>
                        <input
                            id="schedule-start-date"
                            type="datetime-local"
                            value={scheduleForm.start_date}
                            onChange={(e) => handleScheduleFormChange('start_date', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500"
                        />
                    </div>

                    {/* End Date */}
                    <div>
                        <label htmlFor="schedule-end-date" className="block text-sm font-medium text-gray-700 mb-2">
                            End Date
                        </label>
                        <input
                            id="schedule-end-date"
                            type="datetime-local"
                            value={scheduleForm.end_date}
                            onChange={(e) => handleScheduleFormChange('end_date', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500"
                        />
                    </div>

                    {/* State */}
                    <div>
                        <label htmlFor="schedule-state" className="block text-sm font-medium text-gray-700 mb-2">
                            State
                        </label>
                        <select
                            id="schedule-state"
                            value={scheduleForm.state}
                            onChange={(e) => handleScheduleFormChange('state', e.target.value)}
                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-gray-800 focus:outline-none focus:border-blue-500"
                        >
                            <option value="ENABLED">Enabled</option>
                            <option value="DISABLED">Disabled</option>
                        </select>
                    </div>

                    {/* Form Actions */}
                    <div className="flex justify-end gap-2 pt-4">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={scheduleLoading}
                            className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {scheduleLoading ? 'Creating...' : 'Create Schedule'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

ScheduleDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  targetAlias: PropTypes.string.isRequired,
  tenantName: PropTypes.string.isRequired,
  onScheduleCreated: PropTypes.func.isRequired,
  exampleJson: PropTypes.string
};
