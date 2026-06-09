<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { config as backendConfig, user } from '$lib/stores';

	import { getBackendConfig } from '$lib/apis';
	import {
		getImageGenerationModels,
		getImageGenerationConfig,
		updateImageGenerationConfig,
		getConfig,
		updateConfig,
		verifyConfigUrl
	} from '$lib/apis/images';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import CodeEditorModal from '$lib/components/common/CodeEditorModal.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let loading = false;

	let models = null;
	let config = null;

	let showComfyUIWorkflowEditor = false;

	// Dynamic workflow node config — populated automatically by parseAndPopulateWorkflowNodes()
	let workflowNodesConfig: { type: string; key: string; node_ids: string; class_type: string }[] =
		[];
	let lastKnownWorkflowString: string | null = null;

	/**
	 * Scans every node in the parsed ComfyUI API workflow object and builds a configurable
	 * row for each primitive input (string / number / boolean). Array-valued inputs are
	 * wires/links and are intentionally skipped.
	 *
	 * @param workflow       - Parsed JSON object (ComfyUI API format).
	 * @param savedNodes     - Previously-saved node configs used for reconciliation on load.
	 * @param showToast      - Whether to surface success/warning toasts to the user.
	 */
	function parseAndPopulateWorkflowNodes(
		workflow: Record<string, any>,
		savedNodes: { type: string; key: string; node_ids: string[] | string }[] = [],
		showToast = false
	): boolean {
		if (!workflow || typeof workflow !== 'object') {
			if (showToast) toast.error($i18n.t('Invalid workflow data provided for parsing.'));
			workflowNodesConfig = [];
			return false;
		}

		// Each entry is keyed by "nodeId::class_type::inputKey" so that nodes
		// sharing the same class and input (e.g. positive vs negative CLIPTextEncode)
		// are always kept as separate rows rather than merged together.
		const nodeGroups = new Map<
			string,
			{ type: string; key: string; node_ids: string[]; class_type: string }
		>();
		let discoveredPrimitiveCount = 0;

		try {
			for (const nodeId of Object.keys(workflow)) {
				const node = workflow[nodeId];
				if (!node || typeof node !== 'object' || !node.inputs || typeof node.inputs !== 'object')
					continue;

				for (const inputKey of Object.keys(node.inputs)) {
					const val = node.inputs[inputKey];
					const valType = typeof val;

					// Only expose primitive (non-link) inputs
					if (valType !== 'string' && valType !== 'number' && valType !== 'boolean') continue;

					discoveredPrimitiveCount++;

					// Unique key per node+input — never merges across different node IDs
					const entryKey = `${nodeId}::${node.class_type}::${inputKey}`;
					// The "type" stored in COMFYUI_WORKFLOW_NODES uses class_type::inputKey
					const semanticType = `${node.class_type}::${inputKey}`;

					// Check if this entry had saved node IDs the user configured
					const saved = savedNodes.find(
						(s) =>
							s.type === semanticType &&
							s.key === inputKey &&
							Array.isArray(s.node_ids) &&
							s.node_ids.length > 0 &&
							(s.node_ids as string[]).includes(nodeId)
					);

					if (!nodeGroups.has(entryKey)) {
						// Keys that map to payload.prompt in _apply_workflow_nodes are ambiguous
						// when multiple nodes share the same key (e.g. positive vs negative
						// CLIPTextEncode both have key 'text'). Leave node_ids empty for
						// these so the admin explicitly picks which nodes receive the prompt.
						const ambiguousKeys = new Set(['text', 'prompt', 'positive']);
						const autoAssign = !ambiguousKeys.has(inputKey);

						nodeGroups.set(entryKey, {
							type: semanticType,
							key: inputKey,
							node_ids: autoAssign ? [nodeId] : [],
							class_type: node.class_type
						});
					}
				}
			}
		} catch (err) {
			console.error('Error parsing workflow nodes:', err);
			if (showToast) toast.error($i18n.t('Error occurred during workflow parsing.'));
			workflowNodesConfig = [];
			return false;
		}

		// Convert map → array, joining node_ids to comma-separated string for the UI input fields
		workflowNodesConfig = Array.from(nodeGroups.values()).map((n) => ({
			...n,
			node_ids: n.node_ids.join(',')
		}));

		if (showToast) {
			if (workflowNodesConfig.length > 0) {
				toast.success(
					$i18n.t(
						`Workflow parsed. {{count}} configurable input(s) found. Please review the Node IDs.`,
						{ count: workflowNodesConfig.length }
					)
				);
			} else if (discoveredPrimitiveCount === 0 && Object.keys(workflow).length > 0) {
				toast.info(
					$i18n.t(
						'Workflow parsed, but no configurable primitive inputs were found. Ensure you exported in API format.'
					)
				);
			}
		}
		return true;
	}

	/**
	 * Reads config.COMFYUI_WORKFLOW, validates it, and triggers node auto-detection.
	 * @param showToast   - Surface toasts to the user.
	 * @param isNewImport - When true, ignore previously-saved node IDs (fresh import).
	 */
	const parseWorkflowAndUpdateNodes = (showToast = false, isNewImport = false) => {
		const wfString: string = config.COMFYUI_WORKFLOW ?? '';

		// Skip if nothing changed (unless it's an explicit new import)
		if (showToast && wfString === lastKnownWorkflowString && !isNewImport) return;

		if (wfString.trim() === '') {
			workflowNodesConfig = [];
			lastKnownWorkflowString = wfString;
			return;
		}

		try {
			const parsed = JSON.parse(wfString);
			const isValidApiFormat = Object.values(parsed).some(
				(n: any) => n && typeof n === 'object' && n.class_type && n.inputs
			);

			if (!isValidApiFormat) {
				workflowNodesConfig = [];
				if (showToast)
					toast.warning(
						$i18n.t(
							'Not a valid ComfyUI API Workflow JSON format. Make sure to export as API format from ComfyUI.'
						)
					);
				return;
			}

			const reconcileWith = isNewImport ? [] : (config.COMFYUI_WORKFLOW_NODES ?? []);
			const ok = parseAndPopulateWorkflowNodes(parsed, reconcileWith, showToast);
			if (ok) lastKnownWorkflowString = wfString;
		} catch {
			workflowNodesConfig = [];
			if (showToast) toast.error($i18n.t('Invalid JSON syntax in ComfyUI Workflow.'));
		}
	};

	let showComfyUIEditWorkflowEditor = false;

	// Dynamic edit-workflow node config
	let editWorkflowNodesConfig: {
		type: string;
		key: string;
		node_ids: string;
		class_type: string;
	}[] = [];
	let lastKnownEditWorkflowString: string | null = null;

	/**
	 * Same as parseWorkflowAndUpdateNodes but operates on the edit-workflow config.
	 */
	const parseEditWorkflowAndUpdateNodes = (showToast = false, isNewImport = false) => {
		const wfString: string = config.IMAGES_EDIT_COMFYUI_WORKFLOW ?? '';

		if (showToast && wfString === lastKnownEditWorkflowString && !isNewImport) return;

		if (wfString.trim() === '') {
			editWorkflowNodesConfig = [];
			lastKnownEditWorkflowString = wfString;
			return;
		}

		try {
			const parsed = JSON.parse(wfString);
			const isValidApiFormat = Object.values(parsed).some(
				(n: any) => n && typeof n === 'object' && n.class_type && n.inputs
			);

			if (!isValidApiFormat) {
				editWorkflowNodesConfig = [];
				if (showToast)
					toast.warning(
						$i18n.t(
							'Not a valid ComfyUI API Workflow JSON format. Make sure to export as API format from ComfyUI.'
						)
					);
				return;
			}

			const reconcileWith = isNewImport ? [] : (config.IMAGES_EDIT_COMFYUI_WORKFLOW_NODES ?? []);
			// Re-use the same parsing function, writing to editWorkflowNodesConfig
			const savedNodes = reconcileWith;
			if (!parsed || typeof parsed !== 'object') {
				editWorkflowNodesConfig = [];
				return;
			}
			const nodeGroups = new Map<
				string,
				{ type: string; key: string; node_ids: string[]; class_type: string }
			>();
			for (const nodeId of Object.keys(parsed)) {
				const node = parsed[nodeId];
				if (!node || typeof node !== 'object' || !node.inputs || typeof node.inputs !== 'object')
					continue;
				for (const inputKey of Object.keys(node.inputs)) {
					const val = node.inputs[inputKey];
					const valType = typeof val;
					if (valType !== 'string' && valType !== 'number' && valType !== 'boolean') continue;

					// Unique key per node+input — never merges across different node IDs
					const entryKey = `${nodeId}::${node.class_type}::${inputKey}`;
					const semanticType = `${node.class_type}::${inputKey}`;

					if (!nodeGroups.has(entryKey)) {
						// Same ambiguous-key logic as parseAndPopulateWorkflowNodes
						const ambiguousKeys = new Set(['text', 'prompt', 'positive']);
						const autoAssign = !ambiguousKeys.has(inputKey);

						nodeGroups.set(entryKey, {
							type: semanticType,
							key: inputKey,
							node_ids: autoAssign ? [nodeId] : [],
							class_type: node.class_type
						});
					}
				}
			}
			editWorkflowNodesConfig = Array.from(nodeGroups.values()).map((n) => ({
				...n,
				node_ids: n.node_ids.join(',')
			}));

			if (showToast && editWorkflowNodesConfig.length > 0) {
				toast.success(
					$i18n.t(
						`Workflow parsed. {{count}} configurable input(s) found. Please review the Node IDs.`,
						{ count: editWorkflowNodesConfig.length }
					)
				);
			}
			lastKnownEditWorkflowString = wfString;
		} catch {
			editWorkflowNodesConfig = [];
			if (showToast) toast.error($i18n.t('Invalid JSON syntax in ComfyUI Workflow.'));
		}
	};

	const getModels = async () => {
		models = await getImageGenerationModels(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
	};

	const updateConfigHandler = async () => {
		if (
			config.IMAGE_GENERATION_ENGINE === 'automatic1111' &&
			config.AUTOMATIC1111_BASE_URL === ''
		) {
			toast.error($i18n.t('AUTOMATIC1111 Base URL is required.'));
			config.ENABLE_IMAGE_GENERATION = false;

			return null;
		} else if (config.IMAGE_GENERATION_ENGINE === 'comfyui' && config.COMFYUI_BASE_URL === '') {
			toast.error($i18n.t('ComfyUI Base URL is required.'));
			config.ENABLE_IMAGE_GENERATION = false;

			return null;
		} else if (config.IMAGE_GENERATION_ENGINE === 'openai' && config.IMAGES_OPENAI_API_KEY === '') {
			toast.error($i18n.t('OpenAI API Key is required.'));
			config.ENABLE_IMAGE_GENERATION = false;

			return null;
		} else if (config.IMAGE_GENERATION_ENGINE === 'gemini' && config.IMAGES_GEMINI_API_KEY === '') {
			toast.error($i18n.t('Gemini API Key is required.'));
			config.ENABLE_IMAGE_GENERATION = false;

			return null;
		}

		const res = await updateConfig(localStorage.token, {
			...config,
			AUTOMATIC1111_PARAMS:
				typeof config.AUTOMATIC1111_PARAMS === 'string' && config.AUTOMATIC1111_PARAMS.trim() !== ''
					? JSON.parse(config.AUTOMATIC1111_PARAMS)
					: {},
			IMAGES_OPENAI_API_PARAMS:
				typeof config.IMAGES_OPENAI_API_PARAMS === 'string' &&
				config.IMAGES_OPENAI_API_PARAMS.trim() !== ''
					? JSON.parse(config.IMAGES_OPENAI_API_PARAMS)
					: {}
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			if (res.ENABLE_IMAGE_GENERATION) {
				backendConfig.set(await getBackendConfig());
				getModels();
			}

			return res;
		}

		return null;
	};

	const validateJSON = (json) => {
		try {
			const obj = JSON.parse(json);

			if (obj && typeof obj === 'object') {
				return true;
			}
		} catch (e) {}
		return false;
	};

	const saveHandler = async () => {
		loading = true;

		// Serialize dynamic workflow node configs before saving
		if (config?.COMFYUI_WORKFLOW) {
			if (!validateJSON(config?.COMFYUI_WORKFLOW)) {
				toast.error($i18n.t('Invalid JSON format for ComfyUI Workflow.'));
				loading = false;
				return;
			}
			config.COMFYUI_WORKFLOW_NODES = workflowNodesConfig.map((node) => ({
				type: node.type,
				key: node.key,
				node_ids: node.node_ids.trim() === '' ? [] : node.node_ids.split(',').map((id) => id.trim())
			}));
		}

		if (config?.IMAGES_EDIT_COMFYUI_WORKFLOW) {
			if (!validateJSON(config?.IMAGES_EDIT_COMFYUI_WORKFLOW)) {
				toast.error($i18n.t('Invalid JSON format for ComfyUI Edit Workflow.'));
				loading = false;
				return;
			}
			config.IMAGES_EDIT_COMFYUI_WORKFLOW_NODES = editWorkflowNodesConfig.map((node) => ({
				type: node.type,
				key: node.key,
				node_ids: node.node_ids.trim() === '' ? [] : node.node_ids.split(',').map((id) => id.trim())
			}));
		}

		const res = await updateConfigHandler();
		if (res) {
			dispatch('save');
		}

		loading = false;
	};

	onMount(async () => {
		if ($user?.role === 'admin') {
			const res = await getConfig(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (res) {
				config = res;
			}

			if (!config) {
				return;
			}

			if (config.ENABLE_IMAGE_GENERATION) {
				getModels();
			}

			// Pretty-print stored workflow JSON for the code editor
			if (config.COMFYUI_WORKFLOW) {
				try {
					config.COMFYUI_WORKFLOW = JSON.stringify(JSON.parse(config.COMFYUI_WORKFLOW), null, 2);
				} catch (e) {
					console.error(e);
				}
				// Auto-parse on load, reconciling with any saved node configs
				parseWorkflowAndUpdateNodes(false, false);
			}

			if (config.IMAGES_EDIT_COMFYUI_WORKFLOW) {
				try {
					config.IMAGES_EDIT_COMFYUI_WORKFLOW = JSON.stringify(
						JSON.parse(config.IMAGES_EDIT_COMFYUI_WORKFLOW),
						null,
						2
					);
				} catch (e) {
					console.error(e);
				}
				parseEditWorkflowAndUpdateNodes(false, false);
			}

			config.IMAGES_OPENAI_API_PARAMS =
				typeof config.IMAGES_OPENAI_API_PARAMS === 'object'
					? JSON.stringify(config.IMAGES_OPENAI_API_PARAMS ?? {}, null, 2)
					: config.IMAGES_OPENAI_API_PARAMS;

			config.AUTOMATIC1111_PARAMS =
				typeof config.AUTOMATIC1111_PARAMS === 'object'
					? JSON.stringify(config.AUTOMATIC1111_PARAMS ?? {}, null, 2)
					: config.AUTOMATIC1111_PARAMS;
		}
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveHandler();
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden pr-2">
		{#if config}
			<div>
				<div class="mb-3">
					<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('General')}</div>

					<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

					<div class="mb-2.5">
						<div class="flex w-full justify-between items-center">
							<div class="text-xs pr-2">
								<div class="">
									{$i18n.t('Image Generation')}
								</div>
							</div>

							<Switch bind:state={config.ENABLE_IMAGE_GENERATION} />
						</div>
					</div>
				</div>

				<div class="mb-3">
					<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Create Image')}</div>

					<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

					{#if config.ENABLE_IMAGE_GENERATION}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="shrink-0">
										{$i18n.t('Model')}
									</div>
								</div>

								<Tooltip content={$i18n.t('Enter Model ID')} placement="top-start">
									<input
										list="model-list"
										class=" text-right text-sm bg-transparent outline-hidden max-w-full w-52"
										bind:value={config.IMAGE_GENERATION_MODEL}
										placeholder={$i18n.t('Select a model')}
										required
									/>

									<datalist id="model-list">
										{#each models ?? [] as model}
											<option value={model.id}>{model.name}</option>
										{/each}
									</datalist>
								</Tooltip>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="shrink-0">
										{$i18n.t('Image Size')}
									</div>
								</div>

								<Tooltip content={$i18n.t('Enter Image Size (e.g. 512x512)')} placement="top-start">
									<input
										class="  text-right text-sm bg-transparent outline-hidden max-w-full w-52"
										placeholder={$i18n.t('Enter Image Size (e.g. 512x512)')}
										bind:value={config.IMAGE_SIZE}
									/>
								</Tooltip>
							</div>
						</div>

						{#if ['comfyui', 'automatic1111', ''].includes(config?.IMAGE_GENERATION_ENGINE)}
							<div class="mb-2.5">
								<div class="flex w-full justify-between items-center">
									<div class="text-xs pr-2">
										<div class="">
											{$i18n.t('Steps')}
										</div>
									</div>

									<Tooltip
										content={$i18n.t('Enter Number of Steps (e.g. 50)')}
										placement="top-start"
									>
										<input
											class=" text-right text-sm bg-transparent outline-hidden"
											placeholder={$i18n.t('Enter Number of Steps (e.g. 50)')}
											bind:value={config.IMAGE_STEPS}
											required
										/>
									</Tooltip>
								</div>
							</div>
						{/if}

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="">
										{$i18n.t('Image Prompt Generation')}
									</div>
								</div>

								<Switch bind:state={config.ENABLE_IMAGE_PROMPT_GENERATION} />
							</div>
						</div>
					{/if}

					<div class="mb-2.5">
						<div class="flex w-full justify-between items-center">
							<div class="text-xs pr-2">
								<div class="">
									{$i18n.t('Image Generation Engine')}
								</div>
							</div>

							<select
								class="w-fit pr-8 cursor-pointer rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
								bind:value={config.IMAGE_GENERATION_ENGINE}
								placeholder={$i18n.t('Select Engine')}
							>
								<option value="openai">{$i18n.t('Default (Open AI)')}</option>
								<option value="comfyui">{$i18n.t('ComfyUI')}</option>
								<option value="automatic1111">{$i18n.t('Automatic1111')}</option>
								<option value="gemini">{$i18n.t('Gemini')}</option>
							</select>
						</div>
					</div>

					{#if config?.IMAGE_GENERATION_ENGINE === 'openai'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Base URL')}
											bind:value={config.IMAGES_OPENAI_API_BASE_URL}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('API Key')}
											bind:value={config.IMAGES_OPENAI_API_KEY}
											required={false}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Version')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Version')}
											bind:value={config.IMAGES_OPENAI_API_VERSION}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Additional Parameters')}
									</div>
								</div>
							</div>
							<div class="mt-1.5 flex w-full">
								<div class="flex-1 mr-2">
									<Textarea
										className="rounded-lg w-full py-2 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
										bind:value={config.IMAGES_OPENAI_API_PARAMS}
										placeholder={$i18n.t('Enter additional parameters in JSON format')}
										minSize={100}
									/>
								</div>
							</div>
						</div>
					{:else if (config?.IMAGE_GENERATION_ENGINE ?? 'automatic1111') === 'automatic1111'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('AUTOMATIC1111 Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1 mr-2">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('Enter URL (e.g. http://127.0.0.1:7860/)')}
											bind:value={config.AUTOMATIC1111_BASE_URL}
										/>
									</div>
									<button
										class="  transition"
										type="button"
										aria-label="verify connection"
										on:click={async () => {
											await updateConfigHandler();
											const res = await verifyConfigUrl(localStorage.token).catch((error) => {
												toast.error(`${error}`);
												return null;
											});

											if (res) {
												toast.success($i18n.t('Server connection verified'));
											}
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="w-4 h-4"
										>
											<path
												fill-rule="evenodd"
												d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
												clip-rule="evenodd"
											/>
										</svg>
									</button>
								</div>
							</div>

							<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Include `--api` flag when running stable-diffusion-webui')}
								<a
									class=" text-gray-300 font-medium"
									href="https://github.com/AUTOMATIC1111/stable-diffusion-webui/discussions/3734"
									target="_blank"
								>
									{$i18n.t('(e.g. `sh webui.sh --api`)')}
								</a>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('AUTOMATIC1111 Api Auth String')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('Enter api auth string (e.g. username:password)')}
											bind:value={config.AUTOMATIC1111_API_AUTH}
											required={false}
										/>
									</div>
								</div>
							</div>

							<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Include `--api-auth` flag when running stable-diffusion-webui')}
								<a
									class=" text-gray-300 font-medium"
									href="https://github.com/AUTOMATIC1111/stable-diffusion-webui/discussions/13993"
									target="_blank"
								>
									{$i18n
										.t('(e.g. `sh webui.sh --api --api-auth username_password`)')
										.replace('_', ':')}
								</a>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Additional Parameters')}
									</div>
								</div>
							</div>
							<div class="mt-1.5 flex w-full">
								<div class="flex-1 mr-2">
									<Textarea
										className="rounded-lg w-full py-2 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
										bind:value={config.AUTOMATIC1111_PARAMS}
										placeholder={$i18n.t('Enter additional parameters in JSON format')}
										minSize={100}
									/>
								</div>
							</div>
						</div>
					{:else if config?.IMAGE_GENERATION_ENGINE === 'comfyui'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1 mr-2">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('Enter URL (e.g. http://127.0.0.1:7860/)')}
											bind:value={config.COMFYUI_BASE_URL}
										/>
									</div>
									<button
										class="  rounded-lg transition"
										type="button"
										aria-label="verify connection"
										on:click={async () => {
											await updateConfigHandler();
											const res = await verifyConfigUrl(localStorage.token).catch((error) => {
												toast.error(`${error}`);
												return null;
											});

											if (res) {
												toast.success($i18n.t('Server connection verified'));
											}
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="w-4 h-4"
										>
											<path
												fill-rule="evenodd"
												d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
												clip-rule="evenodd"
											/>
										</svg>
									</button>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('sk-1234')}
											bind:value={config.COMFYUI_API_KEY}
											required={false}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<input
								id="upload-comfyui-workflow-input"
								hidden
								type="file"
								accept=".json"
								on:change={(e) => {
									const file = e.target.files[0];
									if (!file) return;
									const reader = new FileReader();
									reader.onload = (ev) => {
										config.COMFYUI_WORKFLOW = ev.target.result as string;
										// Auto-detect nodes from fresh import
										parseWorkflowAndUpdateNodes(true, true);
										(e.target as HTMLInputElement).value = '';
									};
									reader.readAsText(file);
								}}
							/>
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI Workflow')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1 mr-2 justify-end flex gap-1">
										{#if config.COMFYUI_WORKFLOW}
											<button
												class="text-xs text-gray-700 dark:text-gray-400 underline"
												type="button"
												aria-label={$i18n.t('Edit workflow.json content')}
												on:click={() => {
													// open code editor modal
													showComfyUIWorkflowEditor = true;
												}}
											>
												{$i18n.t('Edit')}
											</button>
										{/if}

										<Tooltip content={$i18n.t('Click here to upload a workflow.json file.')}>
											<button
												class="text-xs text-gray-700 dark:text-gray-400 underline"
												type="button"
												aria-label={$i18n.t('Click here to upload a workflow.json file.')}
												on:click={() => {
													document.getElementById('upload-comfyui-workflow-input')?.click();
												}}
											>
												{$i18n.t('Upload')}
											</button>
										</Tooltip>
									</div>
								</div>
							</div>

							<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
								<CodeEditorModal
									bind:show={showComfyUIWorkflowEditor}
									value={config.COMFYUI_WORKFLOW}
									lang="json"
									onChange={(e) => {
										config.COMFYUI_WORKFLOW = e;
										// Re-detect nodes as the user edits JSON
										parseWorkflowAndUpdateNodes(false, false);
									}}
									onSave={() => {
										parseWorkflowAndUpdateNodes(true, false);
									}}
								/>
								<!-- {#if config.COMFYUI_WORKFLOW}
									<Textarea
										class="w-full rounded-lg my-1 py-2 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden disabled:text-gray-600 resize-none"
										rows="10"
										bind:value={config.COMFYUI_WORKFLOW}
										required
									/>
								{/if} -->
								{$i18n.t('Make sure to export a workflow.json file as API format from ComfyUI.')}
							</div>
						</div>

						{#if config.COMFYUI_WORKFLOW}
							<div class="mb-2.5">
								<div class="flex w-full justify-between items-center">
									<div class="text-xs pr-2 shrink-0">
										<div class="">
											{$i18n.t('ComfyUI Workflow Nodes')}
										</div>
									</div>
									{#if workflowNodesConfig.length > 0}
										<div class="text-xs text-green-500 dark:text-green-400 flex items-center gap-1">
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 16 16"
												fill="currentColor"
												class="w-3 h-3"
											>
												<path
													fill-rule="evenodd"
													d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
													clip-rule="evenodd"
												/>
											</svg>
											{$i18n.t('Auto-detected')}
										</div>
									{/if}
								</div>

								{#if workflowNodesConfig.length > 0}
									<div class="mt-1 text-xs flex flex-col gap-1.5">
										{#each workflowNodesConfig as node}
											<div class="flex w-full flex-col">
												<div class="shrink-0">
													<div
														class="capitalize line-clamp-1 w-20 text-gray-400 dark:text-gray-500"
														title={node.type}
													>
														{node.class_type}
													</div>
												</div>

												<div class="flex mt-0.5 items-center">
													<div class="">
														<Tooltip content={$i18n.t('Input Key (e.g. text, unet_name, steps)')}>
															<input
																class="py-1 w-24 text-xs bg-transparent outline-hidden"
																placeholder={$i18n.t('Key')}
																bind:value={node.key}
																required
															/>
														</Tooltip>
													</div>

													<div class="px-2 text-gray-400 dark:text-gray-500">:</div>

													<div class="w-full">
														<Tooltip
															content={$i18n.t('Comma separated Node Ids (e.g. 1 or 1,2)')}
															placement="top-start"
														>
															<input
																class="w-full py-1 text-xs bg-transparent outline-hidden"
																placeholder={$i18n.t('Node Ids')}
																bind:value={node.node_ids}
															/>
														</Tooltip>
													</div>
												</div>
											</div>
										{/each}
									</div>
								{:else}
									<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
										{$i18n.t('No configurable inputs detected. Upload a workflow in API format.')}
									</div>
								{/if}

								<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
									{$i18n.t('Node IDs are auto-detected from your workflow. Adjust them if needed.')}
								</div>
							</div>
						{/if}
					{:else if config?.IMAGE_GENERATION_ENGINE === 'gemini'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Gemini Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Base URL')}
											bind:value={config.IMAGES_GEMINI_API_BASE_URL}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Gemini API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('API Key')}
											bind:value={config.IMAGES_GEMINI_API_KEY}
											required={true}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="">
										{$i18n.t('Gemini Endpoint Method')}
									</div>
								</div>

								<select
									class="w-fit pr-8 cursor-pointer rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
									bind:value={config.IMAGES_GEMINI_ENDPOINT_METHOD}
									placeholder={$i18n.t('Select Method')}
								>
									<option value="predict">predict</option>
									<option value="generateContent">generateContent</option>
								</select>
							</div>
						</div>
					{/if}
				</div>

				<div class="mb-3">
					<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Edit Image')}</div>

					<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

					<div class="mb-2.5">
						<div class="flex w-full justify-between items-center">
							<div class="text-xs pr-2">
								<div class="">
									{$i18n.t('Image Edit')}
								</div>
							</div>

							<Switch bind:state={config.ENABLE_IMAGE_EDIT} />
						</div>
					</div>

					{#if config?.ENABLE_IMAGE_GENERATION && config?.ENABLE_IMAGE_EDIT}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="shrink-0">
										{$i18n.t('Model')}
									</div>
								</div>

								<Tooltip content={$i18n.t('Enter Model ID')} placement="top-start">
									<input
										list="model-list"
										class="text-right text-sm bg-transparent outline-hidden max-w-full w-52"
										bind:value={config.IMAGE_EDIT_MODEL}
										placeholder={$i18n.t('Select a model')}
									/>

									<datalist id="model-list">
										{#each models ?? [] as model}
											<option value={model.id}>{model.name}</option>
										{/each}
									</datalist>
								</Tooltip>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="shrink-0">
										{$i18n.t('Image Size')}
									</div>
								</div>

								<Tooltip content={$i18n.t('Enter Image Size (e.g. 512x512)')} placement="top-start">
									<input
										class="text-right text-sm bg-transparent outline-hidden max-w-full w-52"
										placeholder={$i18n.t('Enter Image Size (e.g. 512x512)')}
										bind:value={config.IMAGE_EDIT_SIZE}
									/>
								</Tooltip>
							</div>
						</div>
					{/if}

					<div class="mb-2.5">
						<div class="flex w-full justify-between items-center">
							<div class="text-xs pr-2">
								<div class="">
									{$i18n.t('Image Edit Engine')}
								</div>
							</div>

							<select
								class="w-fit pr-8 cursor-pointer rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
								bind:value={config.IMAGE_EDIT_ENGINE}
								placeholder={$i18n.t('Select Engine')}
							>
								<option value="openai">{$i18n.t('Default (Open AI)')}</option>
								<option value="comfyui">{$i18n.t('ComfyUI')}</option>
								<option value="gemini">{$i18n.t('Gemini')}</option>
							</select>
						</div>
					</div>

					{#if config?.IMAGE_EDIT_ENGINE === 'openai'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Base URL')}
											bind:value={config.IMAGES_EDIT_OPENAI_API_BASE_URL}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('API Key')}
											bind:value={config.IMAGES_EDIT_OPENAI_API_KEY}
											required={false}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('OpenAI API Version')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Version')}
											bind:value={config.IMAGES_EDIT_OPENAI_API_VERSION}
										/>
									</div>
								</div>
							</div>
						</div>
					{:else if config?.IMAGE_EDIT_ENGINE === 'comfyui'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1 mr-2">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('Enter URL (e.g. http://127.0.0.1:7860/)')}
											bind:value={config.IMAGES_EDIT_COMFYUI_BASE_URL}
										/>
									</div>
									<button
										class="  transition"
										type="button"
										aria-label="verify connection"
										on:click={async () => {
											await updateConfigHandler();
											const res = await verifyConfigUrl(localStorage.token).catch((error) => {
												toast.error(`${error}`);
												return null;
											});

											if (res) {
												toast.success($i18n.t('Server connection verified'));
											}
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="w-4 h-4"
										>
											<path
												fill-rule="evenodd"
												d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
												clip-rule="evenodd"
											/>
										</svg>
									</button>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('sk-1234')}
											bind:value={config.IMAGES_EDIT_COMFYUI_API_KEY}
											required={false}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<input
								id="upload-comfyui-edit-workflow-input"
								hidden
								type="file"
								accept=".json"
								on:change={(e) => {
									const file = e.target.files[0];
									if (!file) return;
									const reader = new FileReader();
									reader.onload = (ev) => {
										config.IMAGES_EDIT_COMFYUI_WORKFLOW = ev.target.result as string;
										// Auto-detect nodes from fresh import
										parseEditWorkflowAndUpdateNodes(true, true);
										(e.target as HTMLInputElement).value = '';
									};
									reader.readAsText(file);
								}}
							/>
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('ComfyUI Workflow')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1 mr-2 justify-end flex gap-1">
										{#if config.IMAGES_EDIT_COMFYUI_WORKFLOW}
											<button
												class="text-xs text-gray-700 dark:text-gray-400 underline"
												type="button"
												aria-label={$i18n.t('Edit workflow.json content')}
												on:click={() => {
													// open code editor modal
													showComfyUIEditWorkflowEditor = true;
												}}
											>
												{$i18n.t('Edit')}
											</button>
										{/if}

										<Tooltip content={$i18n.t('Click here to upload a workflow.json file.')}>
											<button
												class="text-xs text-gray-700 dark:text-gray-400 underline"
												type="button"
												aria-label={$i18n.t('Click here to upload a workflow.json file.')}
												on:click={() => {
													document.getElementById('upload-comfyui-edit-workflow-input')?.click();
												}}
											>
												{$i18n.t('Upload')}
											</button>
										</Tooltip>
									</div>
								</div>
							</div>

							<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
								<CodeEditorModal
									bind:show={showComfyUIEditWorkflowEditor}
									value={config.IMAGES_EDIT_COMFYUI_WORKFLOW}
									lang="json"
									onChange={(e) => {
										config.IMAGES_EDIT_COMFYUI_WORKFLOW = e;
										// Re-detect nodes as the user edits JSON
										parseEditWorkflowAndUpdateNodes(false, false);
									}}
									onSave={() => {
										parseEditWorkflowAndUpdateNodes(true, false);
									}}
								/>
								{$i18n.t('Make sure to export a workflow.json file as API format from ComfyUI.')}
							</div>
						</div>

						{#if config.IMAGES_EDIT_COMFYUI_WORKFLOW}
							<div class="mb-2.5">
								<div class="flex w-full justify-between items-center">
									<div class="text-xs pr-2 shrink-0">
										<div class="">
											{$i18n.t('ComfyUI Workflow Nodes')}
										</div>
									</div>
									{#if editWorkflowNodesConfig.length > 0}
										<div class="text-xs text-green-500 dark:text-green-400 flex items-center gap-1">
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 16 16"
												fill="currentColor"
												class="w-3 h-3"
											>
												<path
													fill-rule="evenodd"
													d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
													clip-rule="evenodd"
												/>
											</svg>
											{$i18n.t('Auto-detected')}
										</div>
									{/if}
								</div>

								{#if editWorkflowNodesConfig.length > 0}
									<div class="mt-1 text-xs flex flex-col gap-1.5">
										{#each editWorkflowNodesConfig as node}
											<div class="flex w-full flex-col">
												<div class="shrink-0">
													<div
														class="capitalize line-clamp-1 w-20 text-gray-400 dark:text-gray-500"
														title={node.type}
													>
														{node.class_type}
													</div>
												</div>

												<div class="flex mt-0.5 items-center">
													<div class="">
														<Tooltip content={$i18n.t('Input Key (e.g. text, unet_name, steps)')}>
															<input
																class="py-1 w-24 text-xs bg-transparent outline-hidden"
																placeholder={$i18n.t('Key')}
																bind:value={node.key}
																required
															/>
														</Tooltip>
													</div>

													<div class="px-2 text-gray-400 dark:text-gray-500">:</div>

													<div class="w-full">
														<Tooltip
															content={$i18n.t('Comma separated Node Ids (e.g. 1 or 1,2)')}
															placement="top-start"
														>
															<input
																class="w-full py-1 text-xs bg-transparent outline-hidden"
																placeholder={$i18n.t('Node Ids')}
																bind:value={node.node_ids}
															/>
														</Tooltip>
													</div>
												</div>
											</div>
										{/each}
									</div>
								{:else}
									<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
										{$i18n.t('No configurable inputs detected. Upload a workflow in API format.')}
									</div>
								{/if}

								<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
									{$i18n.t('Node IDs are auto-detected from your workflow. Adjust them if needed.')}
								</div>
							</div>
						{/if}
					{:else if config?.IMAGE_EDIT_ENGINE === 'gemini'}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Gemini Base URL')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="w-full text-sm bg-transparent outline-hidden text-right"
											placeholder={$i18n.t('API Base URL')}
											bind:value={config.IMAGES_EDIT_GEMINI_API_BASE_URL}
										/>
									</div>
								</div>
							</div>
						</div>

						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2 shrink-0">
									<div class="">
										{$i18n.t('Gemini API Key')}
									</div>
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<SensitiveInput
											inputClassName="text-right w-full"
											placeholder={$i18n.t('API Key')}
											bind:value={config.IMAGES_EDIT_GEMINI_API_KEY}
											required={true}
										/>
									</div>
								</div>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex items-center gap-2 whitespace-nowrap {loading
				? ' cursor-not-allowed'
				: ''}"
			type="submit"
			disabled={loading}
		>
			{$i18n.t('Save')}

			{#if loading}
				<span class="shrink-0">
					<Spinner />
				</span>
			{/if}
		</button>
	</div>
</form>
