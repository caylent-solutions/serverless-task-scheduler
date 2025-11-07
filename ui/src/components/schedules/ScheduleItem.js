import { useState, useEffect } from 'react';

export default function ScheduleItem({ schedule }) {
    const [scheduleExpression, setScheduleExpression] = useState(schedule.schedule_expression);

    const handleUpdate = () => {
        fetch(`./tenants/${schedule.tenant_id}/targets/${schedule.target_alias}/schedules/${schedule.schedule_id.split('/')[schedule.schedule_id.split('/').length - 1]}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ ...schedule, schedule_expression: scheduleExpression })
        })
    };

    const handleDelete = () => {
        fetch(`./tenants/${schedule.tenant_id}/targets/${schedule.target_alias}/schedules/${schedule.schedule_id.split('/')[schedule.schedule_id.split('/').length - 1]}`, {
            method: 'DELETE'
        })
    };

    return (
        <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-4">
                {/* Target Alias */}
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-800 truncate">
                        {schedule.target_alias}
                    </h3>
                    <p className="text-gray-500 text-sm truncate">
                        {schedule.description || 'No description'}
                    </p>
                </div>

                {/* Schedule Expression */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <input 
                            type="text" 
                            value={scheduleExpression} 
                            onChange={(e) => setScheduleExpression(e.target.value)}
                            className="flex-1 border border-gray-300 rounded-md px-3 py-1 text-gray-800 focus:outline-none focus:border-blue-500 font-mono text-sm"
                            placeholder="Schedule expression"
                        />
                        <button 
                            onClick={handleUpdate}
                            className="bg-blue-500 text-white border-none rounded-md px-3 py-1 text-sm font-medium cursor-pointer transition-colors hover:bg-blue-600"
                        >
                            Update
                        </button>
                    </div>
                </div>

                {/* State */}
                <div className="flex-shrink-0">
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                        {schedule.state}
                    </span>
                </div>

                {/* Dates */}
                <div className="flex-shrink-0 text-sm text-gray-500 min-w-0">
                    <div className="truncate">
                        {schedule.start_date ? new Date(schedule.start_date).toLocaleDateString() : 'No start'}
                    </div>
                    <div className="truncate">
                        {schedule.end_date ? new Date(schedule.end_date).toLocaleDateString() : 'No end'}
                    </div>
                </div>

                {/* Actions */}
                <div className="flex-shrink-0">
                    <button 
                        onClick={handleDelete}
                        className="bg-red-500 text-white border-none rounded-md px-3 py-1 text-sm font-medium cursor-pointer transition-colors hover:bg-red-600"
                    >
                        Delete
                    </button>
                </div>
            </div>
        </div>
    );
}