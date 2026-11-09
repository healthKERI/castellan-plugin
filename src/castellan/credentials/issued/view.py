# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.view module

Dialog for viewing an issued credential stored on the Castellan server.
"""
import json

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help
from keri.app import connecting
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton,
    EditableTextLabelValue, EditableURLLabelValue, EditableEmailLabelValue,
    EditableAddressLabelValue, EditableDateLabelValue, EditablePhoneLabelValue
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.collapsible import CollapsibleSection
from locksmith.ui.toolkit.widgets.fields import LocksmithLineEdit, LocksmithPlainTextEdit
from locksmith.ui.vault.credentials.schema_utils import parse_schema_fields, parse_edge_requirements
from locksmith.ui.vault.credentials.field_widgets import create_readonly_field_widget

logger = help.ogler.getLogger(__name__)


class ViewIssuedCredentialDialog(LocksmithDialog):
    """Read-only dialog displaying all fields of an issued credential from Castellan."""

    def __init__(self, app, credential: dict, parent = None):
        self.app = app
        self.org = connecting.Organizer(hby=self.app.vault.hby)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        sad = credential.get('sad', {})

        # Add spacing after SAID
        layout.addSpacing(8)

        self._build_credential_info_section(layout, credential)

        # Credential Attributes section (schema-based rendering)
        self._build_credential_attributes_section(layout, credential)

        # Display dynamic fields if present
        dynamic_fields = credential.get('dynamic_fields', [])
        if dynamic_fields:
            # Add spacing before dynamic fields section
            layout.addSpacing(8)

            # Add section header
            dynamic_header = QLabel("Additional Fields")
            dynamic_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #636466;")
            layout.addWidget(dynamic_header)

            # Add each dynamic field
            for field_data in dynamic_fields:
                if isinstance(field_data, dict) and field_data.get('label') and field_data.get('value'):
                    field_widget = self._create_readonly_dynamic_field(field_data)
                    layout.addWidget(field_widget)

            # Add spacing after dynamic fields section
            layout.addSpacing(8)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithButton("Close")

        title_content = QWidget()
        title_content_layout = QVBoxLayout()
        title_content.setLayout(title_content_layout)
        self.title_label = QLabel("Issued Credential")
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)
        title_content_layout.addSpacing(2)

        # Display SAID as a label with copy button
        said = credential.get('said', '')
        said_row = QHBoxLayout()
        said_label = QLabel(said)
        said_label.setStyleSheet(
            "font-family: 'Menlo', 'SF Mono', monospace; "
            "font-size: 12px; "
            "color: #636466;"
        )
        said_label.setWordWrap(False)
        said_row.addWidget(said_label)
        copy_btn = LocksmithCopyButton(copy_content=said,  icon_size=24)
        copy_btn.setFixedHeight(22)
        copy_btn.setFixedWidth(22)

        said_row.addWidget(copy_btn)
        said_row.addStretch()
        title_content_layout.addLayout(said_row)


        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/out-badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        # Raw JSON in collapsible section
        self._build_raw_json_collapsible(layout, sad)

        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        button_row.addStretch()

        self.setFixedSize(600, 800)


    def _build_credential_info_section(self, layout, credential):
        """Build the credential information section as a bordered, rounded QFrame."""
        schema = credential.get('schema', {})
        schema_title = schema.get('title', '')

        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {colors.BORDER};
                border-radius: 8px;
                background-color: {colors.BACKGROUND_CONTENT};
            }}
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(10)

        # Title
        info_title = QLabel("Credential Information")
        info_title.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        info_layout.addWidget(info_title)

        # Schema
        schema_row = QHBoxLayout()
        schema_label = QLabel("Schema:")
        schema_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        schema_row.addWidget(schema_label)

        schema_value = QLabel(schema_title)
        schema_value.setStyleSheet("font-size: 13px; border: none;")
        schema_row.addWidget(schema_value)
        schema_row.addStretch()
        info_layout.addLayout(schema_row)

        # Issuer
        issuer_pre = credential['sad']['i']
        issuer_alias = None
        try:
            for hab_pre, hab in self.app.vault.hby.habs.items():
                if hab.pre == issuer_pre:
                    issuer_alias = hab.name
                    break
        except:
            pass

        issuer_label = QLabel("Issuer")
        issuer_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none; margin-top: 10px;")
        info_layout.addWidget(issuer_label)

        issuer_container = QWidget()
        issuer_container.setStyleSheet("border: none;")
        issuer_inner_layout = QVBoxLayout(issuer_container)
        issuer_inner_layout.setContentsMargins(20, 0, 0, 0)
        issuer_inner_layout.setSpacing(5)

        issuer_alias_row = QHBoxLayout()
        issuer_alias_label = QLabel("Alias:")
        issuer_alias_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        issuer_alias_row.addWidget(issuer_alias_label)
        issuer_alias_value = QLabel(issuer_alias if issuer_alias else "N/A")
        issuer_alias_value.setStyleSheet("font-size: 13px; border: none;")
        issuer_alias_row.addWidget(issuer_alias_value)
        issuer_alias_row.addStretch()
        issuer_inner_layout.addLayout(issuer_alias_row)

        issuer_aid_row = QHBoxLayout()
        issuer_aid_label = QLabel("AID:")
        issuer_aid_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        issuer_aid_row.addWidget(issuer_aid_label)
        issuer_aid_value = QLabel(issuer_pre)
        issuer_aid_value.setStyleSheet("font-size: 13px; border: none;")
        issuer_aid_value.setWordWrap(True)
        issuer_aid_row.addWidget(issuer_aid_value)
        issuer_aid_row.addStretch()
        issuer_inner_layout.addLayout(issuer_aid_row)

        info_layout.addWidget(issuer_container)

        # Recipient
        recp = credential.get('recipient', '')
        recipient_pre = credential['sad']['a']['i']
        recipient_alias = None
        if recp and (remote_id := self.org.get(recp)) is not None:
            recipient_alias = f'{remote_id['alias']}'

        recipient_label = QLabel("Recipient")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none; margin-top: 10px;")
        info_layout.addWidget(recipient_label)

        recipient_container = QWidget()
        recipient_container.setStyleSheet("border: none;")
        recipient_inner_layout = QVBoxLayout(recipient_container)
        recipient_inner_layout.setContentsMargins(20, 0, 0, 0)
        recipient_inner_layout.setSpacing(5)

        recipient_alias_row = QHBoxLayout()
        recipient_alias_label = QLabel("Alias:")
        recipient_alias_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        recipient_alias_row.addWidget(recipient_alias_label)
        recipient_alias_value = QLabel(recipient_alias if recipient_alias else "N/A")
        recipient_alias_value.setStyleSheet("font-size: 13px; border: none;")
        recipient_alias_row.addWidget(recipient_alias_value)
        recipient_alias_row.addStretch()
        recipient_inner_layout.addLayout(recipient_alias_row)

        recipient_aid_row = QHBoxLayout()
        recipient_aid_label = QLabel("AID:")
        recipient_aid_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        recipient_aid_row.addWidget(recipient_aid_label)
        recipient_aid_value = QLabel(recipient_pre)
        recipient_aid_value.setStyleSheet("font-size: 13px; border: none;")
        recipient_aid_value.setWordWrap(True)
        recipient_aid_row.addWidget(recipient_aid_value)
        recipient_aid_row.addStretch()
        recipient_inner_layout.addLayout(recipient_aid_row)

        info_layout.addWidget(recipient_container)

        # Status
        status_text = credential.get("status", {})

        status_row = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        status_row.addWidget(status_label)

        status_value = QLabel(status_text)
        status_value.setStyleSheet("font-size: 13px; border: none;")
        status_row.addWidget(status_value)
        status_row.addStretch()
        info_layout.addLayout(status_row)

        # Issued Date
        dt = helping.fromIso8601(credential.get('created_at', ''))

        date_row = QHBoxLayout()
        date_label = QLabel("Issued Date:")
        date_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        date_row.addWidget(date_label)

        date_value = QLabel(dt.strftime("%b %d, %Y %I:%M %p"))
        date_value.setStyleSheet("font-size: 13px; border: none;")
        date_row.addWidget(date_value)
        date_row.addStretch()
        info_layout.addLayout(date_row)

        layout.addWidget(info_frame)

    def _build_credential_attributes_section(self, layout, credential):
        """Build credential attributes section with schema-based rendering."""
        # Section header
        layout.addSpacing(8)
        fields_label = QLabel("Credential Attributes")
        fields_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(fields_label)
        layout.addSpacing(10)

        sad = credential.get('sad', {})

        try:
            # Get schema SAID from credential
            schema_said = sad.get('s', '')
            if not schema_said:
                self._build_attributes_fallback(layout, sad)
                return

            # Parse schema fields
            field_defs = parse_schema_fields(self.app.vault.hby, schema_said)

            if not field_defs:
                self._build_attributes_fallback(layout, sad)
                return

            # Get attribute values from credential
            attributes = sad.get('a', {})

            # Create read-only widget for each field
            for field_def in field_defs:
                # Get value from credential or use const default
                value = attributes.get(field_def.name)
                if value is None and field_def.const is not None:
                    value = field_def.const

                # Create read-only field widget
                widget = create_readonly_field_widget(field_def, value)
                layout.addWidget(widget)
                layout.addSpacing(10)

            # Handle edge credentials if present
            edge_defs = parse_edge_requirements(self.app.vault.hby, schema_said)
            if edge_defs and 'e' in sad:
                self._build_edge_credentials_section(layout, sad, edge_defs)

        except Exception as e:
            logger.error(f"Failed to parse schema for field rendering: {e}")
            self._build_attributes_fallback(layout, sad)

    def _build_edge_credentials_section(self, layout, sad, edge_defs):
        """Build section showing edge (chained) credentials."""
        layout.addSpacing(15)

        edges_label = QLabel("Chained Credentials")
        edges_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(edges_label)
        layout.addSpacing(10)

        edge_data = sad.get('e', {})

        for edge_def in edge_defs:
            if edge_def.name in edge_data:
                edge_info = edge_data[edge_def.name]
                cred_said = edge_info.get('n', 'N/A')

                # Create read-only field
                edge_field = LocksmithLineEdit(edge_def.description)
                edge_field.setText(cred_said)
                edge_field.setReadOnly(True)
                edge_field.setCursorPosition(0)
                edge_field.setMinimumWidth(420)
                edge_field.setStyleSheet("""
                    QLineEdit {
                        background-color: #F5F5F5;
                        border: 1px solid #CCCCCC;
                        border-radius: 6px;
                        padding: 8px;
                        font-size: 13px;
                    }
                """)

                layout.addWidget(edge_field)
                layout.addSpacing(10)

    def _build_attributes_fallback(self, layout, sad):
        """Fallback display when schema parsing fails - show attributes as simple key/value pairs."""
        attributes = sad.get('a', {})
        if not attributes:
            no_attrs_label = QLabel("No attributes available")
            no_attrs_label.setStyleSheet("font-size: 13px; color: #636466;")
            layout.addWidget(no_attrs_label)
            return

        for key, value in attributes.items():
            # Skip internal fields
            if key in ('i', 'd'):
                continue

            row = QHBoxLayout()
            key_label = QLabel(f"{key}:")
            key_label.setStyleSheet("font-weight: 500; font-size: 13px;")
            key_label.setFixedWidth(120)
            row.addWidget(key_label)

            value_str = str(value) if not isinstance(value, str) else value
            value_label = QLabel(value_str)
            value_label.setStyleSheet("font-size: 13px;")
            value_label.setWordWrap(True)
            row.addWidget(value_label)
            row.addStretch()

            layout.addLayout(row)
            layout.addSpacing(5)

    def _build_raw_json_collapsible(self, layout, sad):
        """Build collapsible section for raw JSON view."""
        layout.addSpacing(15)

        # Create collapsible section
        self.json_collapsible_section = CollapsibleSection(title="View Raw JSON")

        # Content layout
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)

        # Copy button
        credential_json = json.dumps(sad, indent=2)
        copy_row = QHBoxLayout()
        self.copy_json_button = LocksmithCopyButton(copy_content=credential_json, icon_size=24)
        copy_row.addStretch()
        copy_row.addWidget(self.copy_json_button)
        content_layout.addLayout(copy_row)

        # JSON text field
        self.json_field = LocksmithPlainTextEdit()
        self.json_field.setPlainText(credential_json)
        self.json_field.setReadOnly(True)
        self.json_field.setFixedHeight(200)
        self.json_field.setMaximumWidth(480)
        font = self.json_field.font()
        font.setFamily("Menlo, SF Mono, Monaco, Courier New, monospace")
        font.setPointSize(11)
        self.json_field.setFont(font)
        content_layout.addWidget(self.json_field)

        self.json_collapsible_section.set_content_layout(content_layout)
        layout.addWidget(self.json_collapsible_section)
        self.register_collapsible_section(self.json_collapsible_section)

    @staticmethod
    def _add_field_row(layout: QVBoxLayout, label: str, value: str,
                       monospace: bool = False, copyable: bool = False):
        field_label = QLabel(label)
        field_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(field_label)

        row = QHBoxLayout()
        field = LocksmithLineEdit()
        field.setText(value)
        field.setReadOnly(True)
        if monospace:
            field.setStyleSheet(field.styleSheet() + "font-family: 'Menlo', 'SF Mono', monospace;")
        row.addWidget(field)

        if copyable:
            copy_btn = LocksmithCopyButton(copy_content=value)
            row.addWidget(copy_btn)

        layout.addLayout(row)

    @staticmethod
    def _create_readonly_dynamic_field(field_data: dict) -> QWidget:
        """
        Create a read-only dynamic field widget based on field type.

        Args:
            field_data: Dict with 'label', 'value', and 'type' keys

        Returns:
            Read-only widget displaying the field
        """
        label = field_data.get('label', 'Field')
        value = field_data.get('value', '')
        field_type = field_data.get('type', 'text').lower()

        # Map type to appropriate component class
        type_map = {
            'text': EditableTextLabelValue,
            'url': EditableURLLabelValue,
            'email': EditableEmailLabelValue,
            'address': EditableAddressLabelValue,
            'date': EditableDateLabelValue,
            'phone': EditablePhoneLabelValue,
        }

        # Get component class (default to text if unknown type)
        ComponentClass = type_map.get(field_type, EditableTextLabelValue)

        # Create component with label and value
        field_widget = ComponentClass(label=label, value=value)

        # Set to read-only mode (no click-to-edit)
        field_widget.setReadOnly(True)

        return field_widget
