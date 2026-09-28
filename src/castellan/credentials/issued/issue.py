# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.credentials.issued.issue module

Dialog for issuing credentials
"""
import qasync
from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QButtonGroup, QCheckBox
from keri import help, core, kering
from keri.app import signing
from keri.core import coring, eventing, parsing
from keri.vc import protocoling
from keri.vdr import eventing as veventing
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithRadioButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from locksmith.ui.vault.credentials.field_widgets import create_editable_field_widget
from locksmith.ui.vault.credentials.schema_utils import parse_schema_fields, parse_edge_requirements
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

from ...core import remoting
from ...core.controls.credentialing import build_credential

logger = help.ogler.getLogger(__name__)


class IssueCredentialDialog(LocksmithDialog):
    """Dialog for issuing a credential."""

    fetch_data = Signal()

    def __init__(self, app, parent=None):
        """
        Initialize the IssueCredentialDialog.

        Args:
            app: Application instance
            parent: Parent widget
        """
        self.app = app
        self._parent = parent

        # Initialize storage for dynamic fields
        self._dynamic_field_widgets = {}
        self._dynamic_fields_start_index = None
        self._const_fields_values = {}
        self._edge_dropdowns = {}  # Store edge credential dropdowns
        self._awaiting_auth = False  # Guard: only handle auth_codes_entered when we initiated auth

        # Create content widget
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #F8F9FF;")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Store reference to content layout for dynamic field insertion
        self.content_layout = layout

        layout.addSpacing(20)

        # Schema Selection
        issuer_label = QLabel("Select Issuer")
        issuer_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(issuer_label)

        self.issuer_dropdown = FloatingLabelComboBox("Issuer")
        self.issuer_dropdown.setFixedWidth(500)
        layout.addWidget(self.issuer_dropdown)

        layout.addSpacing(15)

        # Schema Selection
        issuer_label = QLabel("Select Schema")
        issuer_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(issuer_label)

        self.schema_dropdown = FloatingLabelComboBox("Schema")
        self.schema_dropdown.setFixedWidth(500)
        layout.addWidget(self.schema_dropdown)

        layout.addSpacing(15)

        # Recipient type radio buttons
        recipient_label = QLabel("Recipient Type")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(recipient_label)

        radio_layout = QHBoxLayout()
        self.local_radio = LocksmithRadioButton("Local Identifier")
        self.remote_radio = LocksmithRadioButton("Remote Identifier")
        self.remote_radio.setChecked(True)

        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.remote_radio)
        radio_layout.addSpacing(10)
        radio_layout.addWidget(self.local_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        layout.addSpacing(15)

        # Recipient identifier dropdown
        recipient_id_label = QLabel("Recipient Identifier")
        recipient_id_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(recipient_id_label)

        self.recipient_dropdown = FloatingLabelComboBox("Recipient")
        self.recipient_dropdown.setFixedWidth(400)
        self._populate_recipient_dropdown()
        layout.addWidget(self.recipient_dropdown)

        control_widget = QWidget()
        control_widget.setStyleSheet("background-color: #F8F9FF;")
        self.control_layout = QVBoxLayout(control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(12)

        layout.addWidget(control_widget)
        layout.addStretch()

        # Create button row
        button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Cancel")
        button_row.addWidget(self.cancel_button)
        button_row.addSpacing(10)
        self.issue_button = LocksmithButton("Issue Credential")
        button_row.addWidget(self.issue_button)

        # Create title content
        title_content_widget = QWidget()
        title_content = QHBoxLayout()
        icon = QIcon(":/assets/material-icons/out-badge.svg")
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        icon_label.setFixedSize(32, 32)
        title_content.addWidget(icon_label)

        title_label = QLabel("  Issue Credential")
        title_label.setStyleSheet("font-size: 16px;")
        title_content.addWidget(title_label)
        title_content_widget.setLayout(title_content)

        # Initialize parent dialog
        super().__init__(
            parent=parent,
            title_content=title_content_widget,
            show_close_button=True,
            content=content_widget,
            buttons=button_row,
            show_overlay=False
        )

        self.setFixedSize(650, 800)

        # Create button group for recipient type radios (must be after super().__init__)
        self.recipient_type_group = QButtonGroup(self)
        self.recipient_type_group.addButton(self.local_radio)
        self.recipient_type_group.addButton(self.remote_radio)

        # Connect signals
        self.cancel_button.clicked.connect(self.close)
        self.local_radio.toggled.connect(self._on_recipient_type_changed)
        self.remote_radio.toggled.connect(self._on_recipient_type_changed)
        self.schema_dropdown.currentIndexChanged.connect(self._on_schema_changed)
        self.issue_button.clicked.connect(self._on_issue)

    def showEvent(self, event):
        """Called when the dialog is shown."""
        super().showEvent(event)
        # Populate schema dropdown asynchronously when dialog is displayed
        self.fetch_data.connect(self._load_data_async)
        self.fetch_data.emit()

    @qasync.asyncSlot()
    async def _load_data_async(self):
        """Async slot to load schemas when dialog is shown."""
        await self._populate_schema_dropdown()
        await self._populate_issuer_dropdown()

    async def _populate_schema_dropdown(self):
        """Populate the schema dropdown with schemas from the Castellan server."""
        self.schema_dropdown.clear()
        self.schema_dropdown.addItem("Select a schema...")
        try:
            # Fetch all schemas from the server
            response = await remoting.fetch_schemas(
                app=self.app,
                page=0,
                page_size=1000,  # Get all schemas
            )

            if not response.get('success'):
                error_msg = response.get('error', 'Unknown error')
                logger.error(f"Failed to fetch schemas: {error_msg}")
                self.show_error(f"Failed to load schemas: {error_msg}")
                return

            schemas = response.get('schemas', [])

            for item in schemas:
                said = item.get('said', '')
                schema = item.get('schema', {})
                schema_title = schema.get('title', 'Untitled')
                schema_version = schema.get('version', '')
                # Format: "Title v1.0.0"
                display_text = f"{schema_title}"
                if schema_version:
                    display_text += f" v{schema_version}"

                # Store the full SAID as user data
                self.schema_dropdown.addItem(display_text, userData=said)

        except Exception as e:
            logger.exception(f"Error loading schemas: {e}")
            self.show_error(f"Failed to load schemas: {str(e)}")

    async def _populate_issuer_dropdown(self):
        """Populate the issuer dropdown with multisig issuers from the Castellan server."""
        self.issuer_dropdown.clear()
        self.issuer_dropdown.addItem("Select an issuer...")

        try:
            # Fetch all issuers from the server
            response = await remoting.fetch_multisig_identifiers(
                app=self.app,
                page=0,
                page_size=1000,  # Get all issuers
            )

            if not response.get('success'):
                error_msg = response.get('error', 'Unknown error')
                logger.error(f"Failed to fetch issuers: {error_msg}")
                self.show_error(f"Failed to load issuers: {error_msg}")
                return

            issuers = response.get('identifiers', [])

            for item in issuers:
                aid = item.get('aid', '')
                multisig_id = item.get('id')
                alias = item.get('alias', {})
                registry_pre = item.get('registry', {}).get('registry_pre', '')

                # Format: "Title v1.0.0"
                display_text = f"{alias} ({aid})"

                # Store the full SAID as user data
                self.issuer_dropdown.addItem(display_text,
                                             userData=dict(id=multisig_id, aid=aid, registry_pre=registry_pre))

        except Exception as e:
            logger.exception(f"Error loading issuers: {e}")
            self.show_error(f"Failed to load issuers: {str(e)}")

    def _populate_recipient_dropdown(self):
        """Populate the recipient dropdown based on the selected recipient type."""
        self.recipient_dropdown.clear()
        self.recipient_dropdown.addItem("Select a recipient...")

        try:
            if self.local_radio.isChecked():
                # Populate with local identifiers
                hby = self.app.vault.hby
                for hab_pre, hab in hby.habs.items():
                    # Format: "Name (prefix)"
                    display_text = f"{hab.name} ({hab_pre})"
                    self.recipient_dropdown.addItem(display_text, userData=hab_pre)
            else:
                # Populate with remote identifiers
                remote_ids = self.app.vault.org.list()
                for remote_id in remote_ids:
                    alias = remote_id.get('alias', 'Unknown')
                    pre = remote_id.get('id', '')
                    # Format: "Alias (prefix)"
                    display_text = f"{alias} ({pre})"
                    self.recipient_dropdown.addItem(display_text, userData=pre)

        except Exception as e:
            logger.exception(f"Error loading recipients: {e}")
            self.show_error(f"Failed to load recipients: {str(e)}")

    def _on_recipient_type_changed(self):
        """Handle recipient type radio button selection changes."""
        # Refresh the recipient dropdown when type changes
        self._populate_recipient_dropdown()

    def _parse_rules_from_schema(self, schema_said: str) -> dict:
        """
        Parse schema and extract rules block for credential issuance.

        Args:
            schema_said: SAID of the schema to parse

        Returns:
            Dictionary representing the rules block with const values
        """
        try:
            # Get schema from database using SAID
            schemer = self.app.vault.hby.db.schema.get(keys=(schema_said,))
            if not schemer:
                logger.error(f"Schema {schema_said} not found")
                return {}

            schema = schemer.sed
            props = schema.get('properties', {})

            # Navigate to r.oneOf array
            if 'r' not in props:
                logger.debug("Schema has no 'r' property (no rules)")
                return {}

            r_prop = props['r']

            # Check if r has oneOf
            if 'oneOf' not in r_prop:
                logger.debug("Schema 'r' property has no 'oneOf' structure")
                return {}

            one_of = r_prop['oneOf']

            # Find the object type in the oneOf array
            rules_obj = None
            for item in one_of:
                if isinstance(item, dict) and item.get('type') == 'object':
                    rules_obj = item
                    break

            if not rules_obj:
                logger.debug("No object type found in r.oneOf array")
                return {}

            # Get properties of the rules object
            rules_properties = rules_obj.get('properties', {})

            # Build the rules block (exclude 'd' property)
            rules_block = {'d': ''}
            for prop_name, prop_def in rules_properties.items():
                if prop_name == 'd':
                    continue

                # Recursively extract const values from nested structure
                extracted = self._extract_rules_block(prop_def)
                if extracted:
                    rules_block[prop_name] = extracted  # type: ignore

            _, rules_block = coring.Saider.saidify(sad=rules_block, label='d')
            logger.info(f"Parsed rules block with {len(rules_block)} rules from schema {schema_said}")
            return rules_block

        except Exception as e:
            logger.exception(f"Error parsing rules from schema: {e}")
            self.show_error(f"Failed to parse schema rules: {str(e)}")
            return {}

    def _extract_rules_block(self, prop_def: dict) -> dict | str | None:
        """
        Recursively extract rules block structure from schema property definition.

        Traverses nested objects and extracts 'const' values.

        Args:
            prop_def: Property definition from schema

        Returns:
            Extracted rules structure (dict, string, or None)
        """
        # If this property has a const value, return it directly
        if 'const' in prop_def:
            return prop_def['const']

        # If this property is an object, recursively process its properties
        if prop_def.get('type') == 'object' and 'properties' in prop_def:
            result = {}
            for nested_name, nested_def in prop_def['properties'].items():
                extracted = self._extract_rules_block(nested_def)
                if extracted is not None:
                    result[nested_name] = extracted

            return result if result else None

        # If no const or nested properties, return None
        return None

    def _get_credentials_for_schema(self, schema_said: str) -> list[dict]:
        """
        Get all credentials (issued and received) for a specific schema.

        Args:
            schema_said: SAID of the schema to filter by

        Returns:
            List of credential info dictionaries with 'said' and 'display_name'
        """
        try:
            reger = self.app.vault.rgy.reger
            credentials = []

            # Query credentials by schema SAID
            for (_,), saider in reger.schms.getItemIter(keys=(schema_said,)):
                credential = reger.creds.get(keys=(saider.qb64,))

                if not credential:
                    continue

                # Get schema info for display
                schema_name = "Unknown Schema"
                try:
                    schemer = self.app.vault.hby.db.schema.get(keys=(credential.schema,))
                    if schemer:
                        schema_name = schemer.sed.get('title', 'Unknown Schema')
                except:
                    pass

                cred_said = credential.said
                display_name = f"{schema_name} ({cred_said[:15]}...)"

                credentials.append({
                    'said': cred_said,
                    'display_name': display_name
                })

            logger.debug(f"Found {len(credentials)} credentials for schema {schema_said}")
            return credentials

        except Exception as e:
            logger.exception(f"Error querying credentials for schema: {e}")
            self.show_error(f"Failed to load chained credentials: {str(e)}")
            return []

    def _create_edge_dropdown(self, edge_req) -> FloatingLabelComboBox:
        """
        Create a dropdown for selecting an edge credential.

        Args:
            edge_req: Edge requirement EdgeDefinition with name, description, schema_said

        Returns:
            FloatingLabelComboBox: Dropdown widget populated with matching credentials
        """
        # Add asterisk to indicate required field
        label = f"{edge_req.description} *"

        dropdown = FloatingLabelComboBox(label)
        dropdown.setFixedWidth(400)

        # Add placeholder
        dropdown.addItem("Select a credential...")

        # Get credentials for this schema
        credentials = self._get_credentials_for_schema(edge_req.schema_said)

        # Populate dropdown
        for cred in credentials:
            dropdown.addItem(cred['display_name'], userData=cred['said'])

        return dropdown

    def _create_field_widget(self, field_def) -> QWidget:
        """
        Create appropriate widget for field based on type and format.

        Args:
            field_def: Field definition FieldDefinition with name, type, format, description, required

        Returns:
            QWidget: Appropriate input widget for the field type
        """
        return create_editable_field_widget(field_def)

    def _generate_dynamic_fields(self, schema_said: str):
        """
        Generate dynamic form fields based on selected schema.

        Args:
            schema_said: SAID of the schema to generate fields for
        """
        # Clear previous dynamic fields
        self._clear_dynamic_fields()

        # Reset stored widgets
        self._dynamic_field_widgets = {}
        self._edge_dropdowns = {}

        # Parse schema to get field definitions
        field_defs = parse_schema_fields(self.app.vault.hby, schema_said)

        # Parse edge requirements
        edge_reqs = parse_edge_requirements(self.app.vault.hby, schema_said)

        if not field_defs and not edge_reqs:
            logger.warning(f"No fields or edges to generate for schema {schema_said}")
            return

        # Start adding fields to the control layout
        # First add some space
        self.control_layout.addSpacing(20)

        # Add credential attributes section if there are any fields
        if field_defs:
            # Add section header
            fields_label = QLabel("Credential Attributes")
            fields_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self.control_layout.addWidget(fields_label)

            self.control_layout.addSpacing(15)

            # Generate and add widgets
            for field_def in field_defs:
                if field_def.const is not None:
                    self._const_fields_values[field_def.name] = field_def.const
                    continue

                widget = self._create_field_widget(field_def)
                self.control_layout.addWidget(widget)
                self.control_layout.addSpacing(10)

                # Store reference with field name as key
                self._dynamic_field_widgets[field_def.name] = {
                    'widget': widget,
                    'field_def': field_def
                }

            # Add spacing after attribute fields
            self.control_layout.addSpacing(15)

        # Add chained credentials section if there are edge requirements
        if edge_reqs:
            # Add section header
            edges_label = QLabel("Chained Credentials")
            edges_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self.control_layout.addWidget(edges_label)

            self.control_layout.addSpacing(15)

            # Generate and add edge dropdowns
            for edge_req in edge_reqs:
                dropdown = self._create_edge_dropdown(edge_req)
                self.control_layout.addWidget(dropdown)

                # Store reference with edge name as key
                self._edge_dropdowns[edge_req.name] = {
                    'dropdown': dropdown,
                    'edge_req': edge_req
                }

            # Add spacing after edge dropdowns
            self.control_layout.addSpacing(15)

        logger.info(
            f"Generated {len(self._dynamic_field_widgets)} dynamic fields and {len(self._edge_dropdowns)} edge "
            f"dropdowns for schema {schema_said}")

    def _clear_dynamic_fields(self):
        """Clear all dynamically generated field widgets."""

        # Remove all widgets from dynamic fields section
        # Count backwards to avoid index shifting
        items_to_remove = []
        for i in range(self.control_layout.count()):
            item = self.control_layout.itemAt(i)
            if item and item.widget():
                # Stop at the stretch item (no widget)
                items_to_remove.append(item.widget())

        # Remove collected widgets
        for widget in items_to_remove:
            self.control_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

        for i in reversed(range(self.control_layout.count())):
            item = self.control_layout.itemAt(i)
            if item.spacerItem():
                self.control_layout.takeAt(i)

        # Reset storage
        self._dynamic_field_widgets = {}
        self._edge_dropdowns = {}
        self.control_layout.setSpacing(0)

        logger.debug("Cleared dynamic fields and edge dropdowns")

    def _on_schema_changed(self, index: int):
        """
        Handle schema dropdown selection changes.

        Args:
            index: Selected index in dropdown
        """
        # Clear any previous errors
        self.clear_error()

        # Skip if invalid selection
        if index <= 0:
            logger.info("No schema selected, clearing dynamic fields")
            self._clear_dynamic_fields()
            return

        # Get selected schema SAID
        schema_said = self.schema_dropdown.itemData(index)
        logger.info(f"Selected schema {schema_said}")

        if not schema_said:
            logger.warning("No SAID found for selected schema")
            return

        # Generate fields for this schema
        self._generate_dynamic_fields(schema_said)

    @staticmethod
    def _get_field_value(widget: QWidget, field_def):
        """
        Extract value from a field widget based on its type.

        Args:
            widget: The widget to extract value from
            field_def: Field definition FieldDefinition with type information

        Returns:
            Extracted value (str, int, float, bool, or None)
        """
        field_type = field_def.type
        field_format = field_def.format

        # Date-time fields (wrapped in container)
        if field_type == 'string' and field_format == 'date-time':
            if hasattr(widget, 'input_widget'):
                # Extract from QDateTimeEdit
                dt = widget.input_widget.dateTime()
                return dt.strftime("%b %d, %Y %I:%M %p")  # ISO 8601 format
            return None

        # Array fields (wrapped in container)
        elif field_type == 'array':
            if hasattr(widget, 'input_widget'):
                # Extract from LocksmithTextListWidget
                return widget.input_widget.get_items()
            return []

        # Boolean fields
        elif field_type == 'boolean':
            if isinstance(widget, QCheckBox):
                return widget.isChecked()
            return False

        # Number fields
        elif field_type in ('number', 'integer'):
            text = None
            if hasattr(widget, 'text'):
                text = widget.text().strip()
            if not text:
                return None
            try:
                return int(text) if field_type == 'integer' else float(text)  # type: ignore
            except ValueError:
                return None

        # String fields (FloatingLabelLineEdit)
        else:
            if hasattr(widget, 'text'):
                return widget.text().strip()
            return None

    def _extract_credential_attributes(self) -> dict:
        """
        Extract values from dynamic field widgets to build credential attributes.

        Returns:
            dict: Credential attributes with field names as keys
        """
        attributes = {}

        for field_name, value in self._const_fields_values.items():
            attributes[field_name] = value

        if not hasattr(self, '_dynamic_field_widgets'):
            return attributes

        for field_name, field_info in self._dynamic_field_widgets.items():
            widget = field_info['widget']
            field_def = field_info['field_def']

            value = self._get_field_value(widget, field_def)

            # Only include non-empty values
            if value is not None and value != '':
                attributes[field_name] = value

        return attributes

    def _extract_edge_credentials(self) -> dict:
        """
        Extract selected edge credential SAIDs from dropdowns.

        Returns:
            dict: Edge credentials with edge names as keys and credential SAIDs as values
        """
        edges = {}

        if not hasattr(self, '_edge_dropdowns'):
            return edges

        for edge_name, edge_info in self._edge_dropdowns.items():
            dropdown = edge_info['dropdown']
            edge_req = edge_info['edge_req']

            # Get selected credential SAID from dropdown userData
            current_index = dropdown.currentIndex()
            if current_index > 0:  # Skip placeholder at index 0
                cred_said = dropdown.itemData(current_index)
                if cred_said:
                    edges[edge_name] = {'cred_said': cred_said,
                                        'schema_said': edge_req.schema_said,
                                        'operator': edge_req.operator}

        return edges

    @qasync.asyncSlot()
    async def _on_issue(self):
        """Issue credential.

        If we can satisfy the threshold, get the witness authentication codes and issue the credential.  Otherwise
        create the credential and upload it to the server.

        """
        # Clear any previous errors
        self.clear_error()

        # Validate fields
        if not self._validate_fields():
            return

        try:
            self.issue_button.setEnabled(False)
            self.issue_button.setText("Issuing...")
            self.cancel_button.setEnabled(False)

            # Get hab
            if not self.app.vault or not self.app.vault.hby:
                self.show_error("No local vault available")
                return

            issuers_index = self.issuer_dropdown.currentIndex()
            issuer_data = self.issuer_dropdown.itemData(issuers_index)
            multisig_id = issuer_data.get('id')
            multisig_aid = issuer_data.get('aid')

            hab = self.app.vault.hby.habs.get(multisig_aid)
            if not hab:
                self.show_error(f"Identifier {multisig_aid} is not controlled locally")
                return

            # Get selected values
            schema_index = self.schema_dropdown.currentIndex()
            schema_said = self.schema_dropdown.itemData(schema_index)

            recipient_index = self.recipient_dropdown.currentIndex()
            recipient_pre = self.recipient_dropdown.itemData(recipient_index)

            # Extract dynamic field values
            attributes = self._extract_credential_attributes()

            # Extract edge credential SAIDs
            edges = self._extract_edge_credentials()

            # Parse rules from schema
            rules = self._parse_rules_from_schema(schema_said)

            registry_pre = issuer_data.get('registry_pre')
            registry = self.app.vault.rgy.regs[registry_pre] if registry_pre in self.app.vault.rgy.regs else None
            if not registry:
                self.issue_button.setEnabled(True)
                self.issue_button.setText("Issue Credential")
                self.show_error(f"Registry not found for issuer {multisig_aid}")
                return

            # Create registry locally
            logger.info(f"Creating registry '{registry.name}' for {multisig_aid}")

            creder = build_credential(self.app.vault.hby, hab, attributes, edges, recipient_pre, registry, rules,
                                      schema_said, self.app.vault.verifier)

            iss = veventing.issue(creder.said, registry.regk)

            # Create registry seal
            regd = iss.said
            rseal = {"i": iss.pre, "s": "0", "d": regd}

            # Create and sign IXN to anchor the VCP
            kever = hab.kever
            serder = eventing.interact(pre=kever.prefixer.qb64,
                                       dig=kever.serder.said,
                                       sn=kever.sner.num + 1,
                                       data=[rseal])

            sigers = hab.sign(ser=serder.raw)
            anc = eventing.messagize(serder, sigers=sigers)

            # Get event bytes
            seqner = coring.Seqner(sn=kever.sner.num + 1)
            couple = seqner.qb64b + serder.saidb
            iss_bytes = bytearray(iss.raw)
            iss_bytes.extend(core.Counter(core.Codens.SealSourceCouples, count=1,
                                    gvrsn=kering.Vrsn_1_0).qb64b)
            iss_bytes.extend(couple)

            ixn_bytes = bytes(anc)
            acdc_bytes = signing.serialize(creder, coring.Prefixer(qb64=iss.pre),
                                     core.Number(num=iss.sn, code=core.NumDex.Huge),
                                     coring.Saider(qb64=iss.said))

            reg = self.app.vault.rgy.reger.cloneTvtAt(creder.regi)

            exn, atc = protocoling.ipexGrantExn(hab=hab, recp=creder.issuee, message="",
                                                acdc=acdc_bytes, reg=reg, iss=bytes(iss_bytes), anc=ixn_bytes)
            msg = bytearray(exn.raw)
            msg.extend(atc)

            grant_bytes = bytes(msg)

            # Upload to server
            result = await remoting.issue_multisig_credential(
                app=self.app,
                multisig_id=multisig_id,
                iss_bytes=bytes(iss_bytes),
                ixn_bytes=ixn_bytes,
                credential_bytes=bytes(acdc_bytes),
                grant_bytes=grant_bytes
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to create registry: {error_msg}")
                return

            member_index = hab.smids.index(hab.mhab.pre)
            tholder = hab.kever.tholder


            # If our signature is enough to create the registry, do so, otherwise create without parsing
            if tholder.satisfy([member_index]):
                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                print("Parsing bytes:")
                print(ixn_bytes)
                self.creder = creder
                self.iss_bytes = iss_bytes
                self.acdc_bytes = acdc_bytes
                self.grant_bytes = grant_bytes

                parser = parsing.Parser(
                    kvy=self.app.vault.kvy,
                    local = True
                )
                parser.parse(ixn_bytes)

                self.app.vault.kvy.processEscrows()

                kever = self.app.vault.hby.kevers[hab.pre]
                if not kever.serder.said == serder.said:
                    raise ValueError(f"Credential not issued, there was an error parsing the events")

                self._awaiting_auth = True
                auth_dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=list(hab.kever.wits),
                    auth_only=True,
                    parent=self._parent,
                )
                auth_dialog.open()

            else:

                # Success
                logger.info(f"Registry '{registry.name}' created successfully")
                self.close()

        except Exception as e:
            logger.exception(f"Error creating registry: {e}")
            self.show_error(f"Error creating registry: {str(e)}")

        finally:
            # Restore button state
            self._is_creating = False
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue")
            self.cancel_button.setEnabled(True)

    @qasync.asyncSlot(str, str, dict)
    async def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """

        if doer_name != "AuthenticateWitnessesDoer":
            return

        if event_type == "witness_authentication_failed":
            error = data['error']
            logger.error(f"Failed to issue credential: {error}")
            self.show_error(f"Failed to issue credential: {error}")

            self.issue_button.setEnabled(True)
            self.issue_button.setEnabled(True)
            self.issue_button.setText("Issue")
            return


        logger.info(f"IssueCredentialDialog received doer_event: {doer_name} - {event_type}")
        if not self._awaiting_auth:
            return
        self._awaiting_auth = False

        self.app.vault.signals.doer_event.disconnect(self._on_doer_event)
        issuers_index = self.issuer_dropdown.currentIndex()
        issuer_data = self.issuer_dropdown.itemData(issuers_index)
        multisig_id = issuer_data.get('id')
        multisig_aid = issuer_data.get('aid')

        hab = self.app.vault.hby.habs.get(multisig_aid)
        if not hab:
            self.show_error(f"Identifier {multisig_aid} is not controlled locally")
            return

        ixn_bytes = hab.db.cloneEvtMsg(pre=hab.pre, fn=0, dig=hab.kever.serder.said)

        logger.info("Parsing the credential events")
        parser = parsing.Parser(
            kvy=self.app.vault.kvy,
            rvy=self.app.vault.hby.rvy,
            tvy=self.app.vault.tvy,
            vry=self.app.vault.verifier,
            local=True
        )
        parser.parse(self.iss_bytes)
        parser.parse(self.acdc_bytes)
        parser.parse(self.grant_bytes)

        self.app.vault.kvy.processEscrows()
        self.app.vault.tvy.processEscrows()
        self.app.vault.verifier.processEscrows()

        schemer = self.app.hby.db.schema.get(keys=(self.creder.schema,))
        schema_title = schemer.sed.get('title', 'Untitled')

        logger.info("Done parsing all events, checking for credential")
        if not self.app.vault.rgy.reger.saved.get(keys=(self.creder.said,)):
            logger.error(f"Failed to issue credential: credential not parsed and saved correctly.")
            return

        # Upload to server
        result = await remoting.complete_multisig_credential(
            app=self.app,
            multisig_id=multisig_id,
            ixn_bytes=ixn_bytes,
            body=dict(
                schema_said=self.creder.schema,
                schema_title=schema_title,
                recipient=self.creder.issuee,
                publish=True,

            )
        )

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            self.show_error(f"Failed to issue credential: {error_msg}")
            return

        # Success
        logger.info(f"Credential issued successfully")
        self.close()

    def _validate_fields(self):
        """
        Validate all required fields.

        Returns:
            bool: True if all fields are valid, False otherwise
        """
        # Reset field styles
        self.schema_dropdown.setProperty("error", False)
        self.schema_dropdown.style().unpolish(self.schema_dropdown)
        self.schema_dropdown.style().polish(self.schema_dropdown)

        self.recipient_dropdown.setProperty("error", False)
        self.recipient_dropdown.style().unpolish(self.recipient_dropdown)
        self.recipient_dropdown.style().polish(self.recipient_dropdown)

        failed_fields = []

        # Validate schema selection
        if self.schema_dropdown.currentIndex() <= 0:
            failed_fields.append("Schema")
            self.schema_dropdown.setProperty("error", True)
            self.schema_dropdown.style().unpolish(self.schema_dropdown)
            self.schema_dropdown.style().polish(self.schema_dropdown)

        # Validate recipient selection
        if self.recipient_dropdown.currentIndex() <= 0:
            failed_fields.append("Recipient")
            self.recipient_dropdown.setProperty("error", True)
            self.recipient_dropdown.style().unpolish(self.recipient_dropdown)
            self.recipient_dropdown.style().polish(self.recipient_dropdown)

        # Validate dynamic fields
        if hasattr(self, '_dynamic_field_widgets'):
            for field_name, field_info in self._dynamic_field_widgets.items():
                field_def = field_info['field_def']
                widget = field_info['widget']

                # Only validate required fields
                if not field_def.required:
                    continue

                # Get value based on widget type
                value = self._get_field_value(widget, field_def)

                # Check if empty
                if value is None or value == '' or (isinstance(value, str) and not value.strip()):
                    failed_fields.append(field_def.description)

                    # Set error state on widget
                    if hasattr(widget, 'setProperty'):
                        widget.setProperty("error", True)
                        widget.style().unpolish(widget)
                        widget.style().polish(widget)

        # Validate edge credential selections (all are required)
        # Checks truthiness of self._edge_dropdowns to prevent dropping into this block when self._edge_dropdowns == {}
        if hasattr(self, '_edge_dropdowns') and self._edge_dropdowns:
            chained = False
            for edge_name, edge_info in self._edge_dropdowns.items():
                dropdown = edge_info['dropdown']

                # Check if a credential is selected (index 0 is placeholder)
                if dropdown.currentIndex() > 0:
                    chained = True
                    break

            if not chained:
                failed_fields.append("At least one chained credential is required")
                for edge_name, edge_info in self._edge_dropdowns.items():
                    dropdown = edge_info['dropdown']
                    # Set error state on dropdown
                    dropdown.setProperty("error", True)
                    dropdown.style().unpolish(dropdown)
                    dropdown.style().polish(dropdown)

        if failed_fields:
            field_text = "field" if len(failed_fields) == 1 else "fields"
            self.show_error(f"Please fill in required {field_text}: {', '.join(failed_fields)}")
            return False

        return True


