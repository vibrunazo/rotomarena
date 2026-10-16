"""The models Laya's fine-tune may learn from: open weights whose licenses allow training another model on their
outputs (license files read 16 Oct 2026). Left out: MiniMax M3 (non-commercial grant, silent on models trained on its
outputs), Drex (Open RAIL-M: a model trained on its outputs is a Derivative, and competing decision models are
barred), and every closed model (their terms forbid it).

Each entry: config id -> (credit name, license, OpenRouter model for draft-only entries or None for registry ones,
Hugging Face repo). Muse Spark Open's license asks every model trained on its outputs to show "Built with Muse Spark
Open" and follow Meta's usage policy: `notice` carries that onto the model page."""

SOURCES = {
    # in the RotomArena registry
    "deepseek_v4_1_flash": ("DeepSeek V4.1 Flash", "MIT", None, "deepseek-ai/DeepSeek-V4.1-Flash"),
    "deepseek_v4_pro": ("DeepSeek V4 Pro", "MIT", None, "deepseek-ai/DeepSeek-V4-Pro"),
    "glm_5_3": ("GLM 5.3", "GLM-5.3 License (MIT-style)", None, "zai-org/GLM-5.3"),
    "glm_5_3_flash": ("GLM 5.3 Flash", "MIT", None, "zai-org/GLM-5.3-Flash"),
    "mimo_v2_6_flash": ("MiMo V2.6 Flash", "MIT", None, "XiaomiMiMo/MiMo-V2.6-Flash-RL"),
    "mimo_v2_6_pro": ("MiMo V2.6 Pro", "MIT", None, "XiaomiMiMo/MiMo-V2.6-Pro-RL"),
    "kimi_k3": ("Kimi K3", "Kimi K3 License (MIT-style)", None, "moonshotai/Kimi-K3"),
    "qwen3_8_27b": ("Qwen3.8 27B", "Apache-2.0", None, "Qwen/Qwen3.8-27B"),
    "gemma_4_31b": ("Gemma 4 31B", "Apache-2.0", None, "google/gemma-4-31B-it"),
    "nemotron_3_5_super_vl": ("Nemotron 3.5 Super VL", "OpenMDW-1.1", None, "nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16"),
    "nemotron_3_ultra": ("Nemotron 3 Ultra", "OpenMDW-1.1", None, "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16"),
    "muse_spark_open": ("Muse Spark Open", "Muse Model License", None, "meta-models/Muse-Spark-Open-816B-A42B"),
    "ling_3_1_flash": ("Ling 3.1 Flash", "MIT", None, "inclusionAI/Ling-3.1-flash"),
    "gpt_oss_20b": ("GPT-OSS 20B", "Apache-2.0", None, "openai/gpt-oss-20b"),
    "bonsai_2_27b": ("Bonsai 2 27B", "Apache-2.0", None, "prism-ml/Ternary-Bonsai-2-27B-gguf"),
    "ornith_1_5_35b_a3b": ("Ornith 1.5 35B", "MIT", None, "ornith-ai/ornith-1.5-35b-a3b"),
    "ling_3_0_tiny": ("Ling 3.0 Tiny", "MIT", None, "inclusionai/ling-3.0-tiny"),
    "minicpm5_2b": ("MiniCPM5 2B", "Apache-2.0", None, "openbmb/minicpm5-2b"),
    "granite_4_2_30b": ("Granite 4.2 30B", "Apache-2.0", None, "ibm-granite/granite-4.2-30b"),
    # draft-only: not on the ladder, they only build teams for the lessons
    "beam_1_0": ("Reflection Beam 1.0", "Apache-2.0", "reflection/beam-1.0-501b-a23b", "reflection/Beam-1.0-501B-A23B"),
    "ling_3_0_flash": ("Ling 3.0 Flash", "MIT", "inclusionai/ling-3.0-flash", "inclusionAI/Ling-3.0-flash"),
    "nex_n2_5_pro": ("Nex N2.5 Pro", "Apache-2.0", "nex-agi/nex-n2.5-pro", "nex-agi/Nex-N2.5-Pro"),
    "nex_n2_5_mini": ("Nex N2.5 Mini", "Apache-2.0", "nex-agi/nex-n2.5-mini", "nex-agi/Nex-N2.5-mini"),
    "granite_4_2_8b": ("Granite 4.2 8B", "Apache-2.0", "ibm-granite/granite-4.2-8b", "ibm-granite/granite-4.2-8b"),
    "muse_glimmer_30b": ("Muse Glimmer 30B", "Apache-2.0", "meta/muse-glimmer-30b", "meta-models/Muse-Glimmer-30B"),
    "longcat_2_0": ("LongCat 2.0", "MIT", "meituan/longcat-2.0", "meituan-longcat/LongCat-2.0"),
    "inkling_small": ("Inkling Small", "Apache-2.0", "thinkingmachines/inkling-small", "thinkingmachines/Inkling-Small"),
    "hy3": ("Tencent Hy3", "Apache-2.0", "tencent/hy3", "tencent/Hy3"),
    "glm_5_2": ("GLM 5.2", "MIT", "z-ai/glm-5.2", "zai-org/GLM-5.2"),
}

NOTICES = {
    "muse_spark_open": "Built with Muse Spark Open. Its drafts are used under Meta's Muse Model License and Usage Policy.",
}
