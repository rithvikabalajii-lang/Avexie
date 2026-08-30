<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import dayjs from 'dayjs';
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	import { toast } from 'svelte-sonner';

	import { getAllUsers } from '$lib/apis/users';
	import { getToaaAudits } from '$lib/apis/toaa';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Refresh from '$lib/components/icons/Refresh.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	dayjs.extend(localizedFormat);

	const perPage = 50;
	let ready = false;
	let loading = true;
	let page = 1;
	let previousPage = 1;
	let total = 0;
	let items: any[] = [];
	let users: any[] = [];
	let selectedUser = '';
	let selectedStatus = '';
	let query = '';
	let expandedId: string | null = null;
	let searchTimer: ReturnType<typeof setTimeout>;
	let requestSequence = 0;
	let summary = { pending: 0, success: 0, error: 0, blocked: 0 };

	const loadAudits = async () => {
		const sequence = ++requestSequence;
		loading = true;
		try {
			const response = await getToaaAudits(localStorage.token, {
				userId: selectedUser || undefined,
				status: selectedStatus || undefined,
				query: query.trim() || undefined,
				page,
				limit: perPage
			});
			if (sequence !== requestSequence) return;
			items = response.items ?? [];
			total = response.total ?? 0;
			summary = response.summary ?? summary;
		} catch (error) {
			if (sequence === requestSequence) toast.error(String(error));
		} finally {
			if (sequence === requestSequence) loading = false;
		}
	};

	const resetAndLoad = () => {
		if (page !== 1) {
			page = 1;
		} else {
			loadAudits();
		}
	};

	const handleSearch = () => {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(resetAndLoad, 250);
	};

	const statusClass = (status: string) => {
		if (status === 'success')
			return 'bg-green-50 text-green-700 dark:bg-green-900/25 dark:text-green-300';
		if (status === 'error') return 'bg-red-50 text-red-700 dark:bg-red-900/25 dark:text-red-300';
		if (status === 'blocked')
			return 'bg-amber-50 text-amber-700 dark:bg-amber-900/25 dark:text-amber-300';
		return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
	};

	const duration = (item: any) => {
		if (!item.completed_at) return '—';
		return `${Math.max(0, item.completed_at - item.created_at)} ms`;
	};

	const pretty = (value: any) => JSON.stringify(value ?? null, null, 2);

	$: if (ready && page !== previousPage) {
		previousPage = page;
		loadAudits();
	}

	onMount(async () => {
		const response = await getAllUsers(localStorage.token).catch(() => null);
		users = (response?.users ?? response ?? []).sort((a: any, b: any) =>
			a.name.localeCompare(b.name)
		);
		ready = true;
		await loadAudits();
	});

	onDestroy(() => clearTimeout(searchTimer));
</script>

<div class="flex min-h-full flex-col gap-4 pb-8">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="text-lg font-medium text-gray-900 dark:text-white">Agent action audit</h1>
			<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
				Immutable TOAA records for tools executed by every user and agent session.
			</p>
		</div>
		<button
			type="button"
			class="flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-850"
			on:click={loadAudits}
			aria-label="Refresh audit logs"
		>
			<Refresh className="size-3.5" />
			Refresh
		</button>
	</div>

	<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
		{#each [['Successful', summary.success, 'text-green-600 dark:text-green-400'], ['Errors', summary.error, 'text-red-600 dark:text-red-400'], ['Blocked', summary.blocked, 'text-amber-600 dark:text-amber-400'], ['Pending', summary.pending, 'text-gray-600 dark:text-gray-300']] as card}
			<div class="rounded-xl border border-gray-100 p-3 dark:border-gray-850">
				<div class="text-[11px] uppercase tracking-wide text-gray-400">{card[0]}</div>
				<div class={`mt-1 text-xl font-medium ${card[2]}`}>{card[1]}</div>
			</div>
		{/each}
	</div>

	<div class="flex flex-col gap-2 sm:flex-row">
		<div
			class="flex min-w-0 flex-1 items-center rounded-lg border border-gray-200 px-2 dark:border-gray-800"
		>
			<Search className="size-3.5 shrink-0 text-gray-400" />
			<input
				class="w-full bg-transparent px-2 py-2 text-xs outline-hidden"
				bind:value={query}
				on:input={handleSearch}
				placeholder="Search tool, session, or error"
				aria-label="Search audit logs"
			/>
		</div>
		<select
			class="rounded-lg border border-gray-200 bg-transparent px-2.5 py-2 text-xs dark:border-gray-800"
			bind:value={selectedUser}
			on:change={resetAndLoad}
			aria-label="Filter by user"
		>
			<option value="">All users</option>
			{#each users as account (account.id)}
				<option value={account.id}>{account.name} · {account.email}</option>
			{/each}
		</select>
		<select
			class="rounded-lg border border-gray-200 bg-transparent px-2.5 py-2 text-xs dark:border-gray-800"
			bind:value={selectedStatus}
			on:change={resetAndLoad}
			aria-label="Filter by status"
		>
			<option value="">All statuses</option>
			<option value="success">Success</option>
			<option value="error">Error</option>
			<option value="blocked">Blocked</option>
			<option value="pending">Pending</option>
		</select>
	</div>

	{#if loading && items.length === 0}
		<div class="flex justify-center py-16"><Spinner className="size-5" /></div>
	{:else if items.length === 0}
		<div
			class="rounded-xl border border-dashed border-gray-200 py-16 text-center text-sm text-gray-400 dark:border-gray-800"
		>
			No agent actions match these filters.
		</div>
	{:else}
		<div class="overflow-x-auto rounded-xl border border-gray-100 dark:border-gray-850">
			<table class="w-full min-w-[900px] text-left text-xs">
				<thead
					class="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400 dark:border-gray-850"
				>
					<tr>
						<th class="px-3 py-2 font-normal">Time</th>
						<th class="px-3 py-2 font-normal">User</th>
						<th class="px-3 py-2 font-normal">Agent action</th>
						<th class="px-3 py-2 font-normal">Status</th>
						<th class="px-3 py-2 font-normal">Duration</th>
						<th class="px-3 py-2 font-normal">Session</th>
						<th class="w-10 px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					{#each items as item (item.id)}
						<tr
							class="border-b border-gray-50 text-gray-700 last:border-0 dark:border-gray-850/60 dark:text-gray-300"
						>
							<td class="whitespace-nowrap px-3 py-2.5">{dayjs(item.created_at).format('lll')}</td>
							<td class="max-w-52 px-3 py-2.5">
								<div class="truncate font-medium text-gray-900 dark:text-white">
									{item.user?.name ?? 'Deleted user'}
								</div>
								<div class="truncate text-[10px] text-gray-400">
									{item.user?.email ?? item.user_id}
								</div>
							</td>
							<td class="px-3 py-2.5 font-mono text-[11px] text-gray-900 dark:text-gray-100"
								>{item.tool_name}</td
							>
							<td class="px-3 py-2.5">
								<span class={`rounded-full px-2 py-0.5 capitalize ${statusClass(item.status)}`}
									>{item.status}</span
								>
								{#if item.requires_approval}<span class="ml-1 text-[10px] text-amber-600"
										>approval</span
									>{/if}
							</td>
							<td class="whitespace-nowrap px-3 py-2.5 text-gray-500">{duration(item)}</td>
							<td
								class="max-w-48 truncate px-3 py-2.5 font-mono text-[10px] text-gray-400"
								title={item.session_id}>{item.session_id}</td
							>
							<td class="px-3 py-2.5 text-right">
								<button
									type="button"
									class="rounded-md p-1 hover:bg-gray-100 dark:hover:bg-gray-800"
									on:click={() => (expandedId = expandedId === item.id ? null : item.id)}
									aria-label="Inspect agent action"
								>
									<ChevronDown
										className={`size-3.5 transition ${expandedId === item.id ? 'rotate-180' : ''}`}
									/>
								</button>
							</td>
						</tr>
						{#if expandedId === item.id}
							<tr
								class="border-b border-gray-100 bg-gray-50/70 dark:border-gray-850 dark:bg-gray-950/40"
							>
								<td colspan="7" class="p-3">
									<div class="grid gap-3 lg:grid-cols-2">
										<div>
											<div class="mb-1 text-[10px] uppercase tracking-wide text-gray-400">
												Tool input
											</div>
											<pre
												class="max-h-72 overflow-auto rounded-lg bg-white p-3 text-[11px] whitespace-pre-wrap dark:bg-gray-900">{pretty(
													item.tool_input
												)}</pre>
										</div>
										<div>
											<div class="mb-1 text-[10px] uppercase tracking-wide text-gray-400">
												Tool output
											</div>
											<pre
												class="max-h-72 overflow-auto rounded-lg bg-white p-3 text-[11px] whitespace-pre-wrap dark:bg-gray-900">{pretty(
													item.tool_output
												)}</pre>
										</div>
									</div>
									{#if item.error_detail}
										<div
											class="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300"
										>
											{item.error_detail}
										</div>
									{/if}
									<div class="mt-2 break-all font-mono text-[10px] text-gray-400">
										Audit ID: {item.id}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if total > perPage}
		<Pagination bind:page count={total} {perPage} />
	{/if}
</div>
