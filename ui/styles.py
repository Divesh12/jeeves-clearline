from __future__ import annotations

import streamlit as st


def apply_clearline_theme() -> None:
    st.markdown(
        """
        <style>
        /* App background & base text */
        .stApp,
        [data-testid="stAppViewContainer"] {
            background-color: #f8fafc;
            color: #0f172a;
        }

        [data-testid="stHeader"] {
            background-color: #f8fafc;
        }

        .block-container {
            padding-top: 3.25rem !important;
            padding-bottom: 2.2rem !important;
            max-width: 100% !important;
        }

        /* Sidebar & toggles ("Replay Mode", "External AI (Gemini)") */
        section[data-testid="stSidebar"] {
            background-color: #ffffff;
            border-right: 1px solid #e2e8f0;
            color: #0f172a;
        }
        section[data-testid="stSidebar"] .stMarkdown,
        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        /* Headings, labels & captions */
        h1, h2, h3, h4, h5, h6 {
            color: #0f172a;
            line-height: 1.25 !important;
            overflow: visible !important;
            margin-top: 0.25rem !important;
        }

        [data-testid="stWidgetLabel"] label,
        [data-testid="stWidgetLabel"] p {
            color: #0f172a !important;
            font-weight: 600;
            opacity: 1 !important;
        }

        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            color: #475569 !important;
            opacity: 1 !important;
        }

        /* Alert banners */
        [data-testid="stAlert"] {
            border-radius: 10px;
            opacity: 1 !important;
        }
        [data-testid="stAlert"] p,
        [data-testid="stAlert"] span,
        [data-testid="stAlert"] div {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        /* Tabs */
        [data-baseweb="tab-list"] {
            gap: 8px;
            border-bottom: 1px solid #e2e8f0;
        }
        button[data-baseweb="tab"] {
            background-color: transparent;
            color: #475569;
            font-weight: 600;
            padding: 8px 14px;
        }
        button[data-baseweb="tab"] p,
        button[data-baseweb="tab"] span {
            color: inherit;
        }
        button[data-baseweb="tab"]:hover {
            color: #0f172a;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #1d4ed8;
            border-bottom: 2px solid #1d4ed8;
        }

        /* Expanders */
        [data-testid="stExpander"] {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
        }
        [data-testid="stExpander"] summary {
            background-color: #ffffff;
            color: #0f172a;
            border-radius: 10px;
        }
        [data-testid="stExpander"] summary span,
        [data-testid="stExpander"] summary p {
            color: #0f172a;
            font-weight: 600;
        }

        /* File uploader dropzone & uploaded file name */
        [data-testid="stFileUploader"] section {
            background-color: #ffffff;
            border: 1px dashed #94a3b8;
            border-radius: 10px;
        }
        [data-testid="stFileUploader"] section span,
        [data-testid="stFileUploader"] section small {
            color: #334155;
        }
        [data-testid="stFileUploaderFile"],
        [data-testid="stFileUploaderFile"] div,
        [data-testid="stFileUploaderFile"] span,
        [data-testid="stFileUploaderFile"] small,
        [data-testid="stFileUploaderFileName"] {
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            opacity: 1 !important;
        }

        /* Inputs, textareas & selectboxes / dropdown menus */
        input[type="text"],
        input[type="number"],
        textarea {
            background-color: #ffffff;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
        }
        input::placeholder,
        textarea::placeholder {
            color: #64748b;
        }
        div[data-baseweb="select"] > div {
            background-color: #ffffff;
            color: #0f172a;
            border-color: #cbd5e1;
        }
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] div {
            color: #0f172a;
        }
        ul[data-baseweb="menu"],
        ul[data-baseweb="menu"] li,
        div[data-baseweb="popover"] li {
            background-color: #ffffff !important;
            color: #0f172a !important;
        }
        ul[data-baseweb="menu"] li:hover,
        div[data-baseweb="popover"] li:hover {
            background-color: #eff6ff !important;
            color: #1e3a8a !important;
        }

        /* Keep button labels on a single crisp line */
        button[data-baseweb="button"],
        button[data-baseweb="button"] p,
        button[data-baseweb="button"] span {
            white-space: nowrap !important;
            word-break: keep-all !important;
        }

        /* Secondary buttons */
        button[kind="secondary"],
        [data-testid="stBaseButton-secondary"] {
            background-color: #f8fafc;
            color: #0f172a;
            border: 1px solid #94a3b8;
            border-radius: 8px;
            font-weight: 600;
        }
        button[kind="secondary"]:hover,
        [data-testid="stBaseButton-secondary"]:hover {
            background-color: #e2e8f0;
            color: #0f172a;
            border-color: #64748b;
        }
        button[kind="secondary"] p,
        button[kind="secondary"] span,
        [data-testid="stBaseButton-secondary"] p,
        [data-testid="stBaseButton-secondary"] span {
            color: #0f172a;
        }

        /* Primary buttons */
        button[kind="primary"],
        [data-testid="stBaseButton-primary"],
        button[data-testid="stBaseButton-primaryFormSubmit"],
        [data-testid="stBaseButton-secondaryFormSubmit"] {
            background-color: #1d4ed8;
            color: #ffffff;
            border: 1px solid #1e40af;
            border-radius: 8px;
            font-weight: 600;
        }
        button[kind="primary"]:hover,
        [data-testid="stBaseButton-primary"]:hover,
        button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background-color: #1e40af;
            color: #ffffff;
        }
        button[kind="primary"] p,
        button[kind="primary"] span,
        [data-testid="stBaseButton-primary"] p,
        [data-testid="stBaseButton-primary"] span,
        button[data-baseweb="button"] p,
        button[data-baseweb="button"] span {
            opacity: 1;
        }

        /* Cards */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 12px 14px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }

        /* Badges */
        .cl-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            line-height: 1.25;
            white-space: nowrap;
        }
        .cl-badge-warn {
            background-color: #fef3c7;
            color: #92400e;
            border: 1px solid #fcd34d;
        }
        .cl-badge-err {
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }
        .cl-badge-ok {
            background-color: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }
        .cl-badge-info {
            background-color: #e0f2fe;
            color: #075985;
            border: 1px solid #7dd3fc;
        }
        .cl-badge-tag {
            background-color: #f1f5f9;
            color: #1e293b;
            border: 1px solid #cbd5e1;
        }

        /* Finding & callouts */
        .cl-finding-card {
            background-color: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 10px;
            color: #0f172a;
        }
        .cl-formula-strip {
            background-color: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 7px 10px;
            font-size: 0.83rem;
            color: #0f172a;
            margin-top: 8px;
        }
        .cl-action-banner {
            background-color: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 10px;
            padding: 10px 14px;
            color: #1e3a8a;
            font-size: 0.88rem;
            margin: 6px 0 10px 0;
        }
        .cl-local-card {
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 10px;
            padding: 10px 12px;
            color: #166534;
            font-size: 0.82rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )