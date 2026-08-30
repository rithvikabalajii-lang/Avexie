import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getToaaAudits = async (
	token: string,
	options: {
		userId?: string;
		status?: string;
		query?: string;
		page?: number;
		limit?: number;
	} = {}
) => {
	const params = new URLSearchParams({
		page: String(options.page ?? 1),
		limit: String(options.limit ?? 50)
	});
	if (options.userId) params.set('user_id', options.userId);
	if (options.status) params.set('status', options.status);
	if (options.query) params.set('query', options.query);

	const response = await fetch(`${WEBUI_API_BASE_URL}/toaa/audits/?${params.toString()}`, {
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	});
	if (!response.ok) {
		const error = await response.json().catch(() => ({}));
		throw error?.detail ?? 'Unable to load agent action logs';
	}
	return response.json();
};
