#    Copyright (c) 2013 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import copy
import logging

import re
from django import forms
from django.core.validators import RegexValidator, validate_ipv4_address
from netaddr import all_matching_cidrs, IPNetwork, IPAddress
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import smart_text
from muranodashboard.environments import api
from horizon import exceptions, messages
from openstack_dashboard.api import glance
from openstack_dashboard.api.nova import novaclient
from django.template.defaultfilters import pluralize
import horizon.tables as tables
import horizon.forms as hz_forms
import floppyforms
from django.template.loader import render_to_string
from muranoclient.common import exceptions as muranoclient_exc


LOG = logging.getLogger(__name__)


def with_request(func):
    """The decorator is meant to be used together with `UpdatableFieldsForm':
    apply it to the `update' method of fields inside that form.
    """
    def update(self, initial, request=None, **kwargs):
        initial_request = initial.get('request')
        for key, value in initial.iteritems():
            if key != 'request' and key not in kwargs:
                kwargs[key] = value

        if initial_request:
            LOG.debug("Using 'request' value from initial dictionary")
            func(self, initial_request, **kwargs)
        elif request:
            LOG.debug("Using direct 'request' value")
            func(self, request, **kwargs)
        else:
            LOG.error("No 'request' value passed neither via initial "
                      "dictionary, nor directly")
            raise forms.ValidationError("Can't get a request information")
    return update


def make_yaql_validator(field, form, key, validator_property):
    def validator_func(value):
        data = getattr(form, 'cleaned_data', {})
        data[key] = value
        form.service.update_cleaned_data(data, form=form)
        if not validator_property['expr'].__get__(field):
            raise forms.ValidationError(
                _(validator_property.get('message', '')))

    return validator_func


def get_regex_validator(expr):
    try:
        validator = expr['validators'][0]
        if isinstance(validator, RegexValidator):
            return validator
    except (TypeError, KeyError, IndexError):
        pass
    return None


# This function is needed if we don't want to change existing services
# regexpValidators
def wrap_regex_validator(validator, message):
    def _validator(value):
        try:
            validator(value)
        except forms.ValidationError as e:
            e.messages = [message]
            delattr(e, 'code')
            raise e
    return _validator


def get_murano_images(request):
    images = []
    try:
        # public filter removed
        images, _more = glance.image_list_detailed(request)
    except:
        LOG.error("Error to request image list from glance ")
        exceptions.handle(request, _("Unable to retrieve public images."))
    murano_images = []
    for image in images:
        murano_property = image.properties.get('murano_image_info')
        if murano_property:
            try:
                murano_metadata = json.loads(murano_property)
            except ValueError:
                LOG.warning("JSON in image metadata is not valid. "
                            "Check it in glance.")
                messages.error(request, _("Invalid murano image metadata"))
            else:
                image.murano_property = murano_metadata
                murano_images.append(image)
    return murano_images


class RawProperty(object):
    def __init__(self, key, spec):
        self.key = key
        self.spec = spec

    def finalize(self, form_name, service):
        def _get(field):
            data_ready, value = service.get_data(form_name, self.spec)
            return value if data_ready else field.__dict__[self.key]

        def _set(field, value):
            field.__dict__[self.key] = value

        def _del(field):
            del field.__dict__[self.key]
        return property(_get, _set, _del)


class CustomPropertiesField(forms.Field):
    def __init__(self, description=None, description_title=None,
                 *args, **kwargs):
        self.description = description
        self.description_title = (description_title or
                                  unicode(kwargs.get('label', '')))

        validators = []
        for validator in kwargs.get('validators', []):
            if hasattr(validator, '__call__'):  # single regexpValidator
                validators.append(validator)
            else:  # mixed list of regexpValidator-s and YAQL validators
                expr = validator.get('expr')
                regex_validator = get_regex_validator(expr)
                if regex_validator:
                    validators.append(wrap_regex_validator(
                        regex_validator, validator.get('message', '')))
                elif isinstance(expr, RawProperty):
                    validators.append(validator)
        kwargs['validators'] = validators

        super(CustomPropertiesField, self).__init__(*args, **kwargs)

    def clean(self, value):
        """Skip all validators if field is disabled."""
        # form is assigned in ServiceConfigurationForm.finalize_fields()
        form = self.form
        # the only place to ensure that Service object has up-to-date
        # cleaned_data
        form.service.update_cleaned_data(form.cleaned_data, form=form)
        if getattr(self, 'enabled', True):
            return super(CustomPropertiesField, self).clean(value)
        else:
            return super(CustomPropertiesField, self).to_python(value)

    @classmethod
    def finalize_properties(cls, kwargs, form_name, service):
        props = {}
        for key, value in kwargs.items():
            if isinstance(value, RawProperty):
                props[key] = value.finalize(form_name, service)
                del kwargs[key]
        if props:
            return type(cls.__name__, (cls,), props)
        else:
            return cls


class CharField(forms.CharField, CustomPropertiesField):
    pass


class PasswordField(CharField):
    special_characters = '!@#$%^&*()_+|\/.,~?><:{}'
    password_re = re.compile('^.*(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[%s]).*$'
                             % special_characters)
    has_clone = False
    validate_password = RegexValidator(
        password_re, _('The password must contain at least one letter, one   \
                               number and one special character'), 'invalid')

    @staticmethod
    def get_clone_name(name):
        return name + '-clone'

    def compare(self, name, form_data):
        if self.is_original() and self.required:
            # run compare only for original fields
            # do not run compare for hidden fields (they are not required)
            if form_data.get(name) != form_data.get(self.get_clone_name(name)):
                raise forms.ValidationError(_(u"{0}{1} don't match".format(
                    self.label, pluralize(2))))

    class PasswordInput(forms.PasswordInput):
        class Media:
            js = ('muranodashboard/js/passwordfield.js',)

    def __init__(self, label, *args, **kwargs):
        help_text = kwargs.get('help_text')
        if not help_text:
            help_text = _('Enter a complex password with at least one letter, \
                one number and one special character')

        error_messages = {
            'invalid': self.validate_password.message}
        err_msg = kwargs.get('error_messages')
        if err_msg:
            if err_msg.get('required'):
                error_messages['required'] = err_msg.get('required')

        kwargs.update({
            'min_length': 7,
            'max_length': 255,
            'validators': [self.validate_password],
            'label': label,
            'error_messages': error_messages,
            'help_text': help_text,
            'widget': self.PasswordInput(render_value=True),
        })

        super(PasswordField, self).__init__(*args, **kwargs)

    def __deepcopy__(self, memo):
        result = super(PasswordField, self).__deepcopy__(memo)
        result.error_messages = copy.deepcopy(self.error_messages)
        return result

    def is_original(self):
        return hasattr(self, 'original') and self.original

    def clone_field(self):
        self.has_clone = True
        field = copy.deepcopy(self)
        self.original = True
        field.label = _('Confirm password')
        field.error_messages['required'] = _('Please confirm your password')
        field.help_text = _('Retype your password')
        return field


class IntegerField(forms.IntegerField, CustomPropertiesField):
    pass


class Column(tables.Column):
    template_name = 'common/form-fields/data-grid/input.html'

    def __init__(self, transform, table_name=None, **kwargs):
        if hasattr(self, 'template_name'):
            def _transform(datum):
                context = {'data': getattr(datum, self.name, None),
                           'row_index': str(datum.id),
                           'table_name': table_name,
                           'column_name': self.name}
                return render_to_string(self.template_name, context)
            _transform.__name__ = transform
            transform = _transform
        super(Column, self).__init__(transform, **kwargs)


class CheckColumn(Column):
    template_name = 'common/form-fields/data-grid/checkbox.html'


class RadioColumn(Column):
    template_name = 'common/form-fields/data-grid/radio.html'


# FixME: we need to have separated object until find out way to use the same
# code for MS SQL Cluster datagrid
class Object(object):
    def __init__(self, id, **kwargs):
        self.id = id
        for key, value in kwargs.iteritems():
            setattr(self, key, value)

    def as_dict(self):
        item = {}
        for key, value in self.__dict__.iteritems():
            if key != 'id':
                item[key] = value
        return item


def DataTableFactory(name, columns):
    class Object(object):
        row_name_re = re.compile(r'.*\{0}.*')

        def __init__(self, id, **kwargs):
            self.id = id
            for key, value in kwargs.iteritems():
                if isinstance(value, basestring) and \
                        re.match(self.row_name_re, value):
                    setattr(self, key, value.format(id))
                else:
                    setattr(self, key, value)

    class DataTableBase(tables.DataTable):
        def __init__(self, request, data, **kwargs):
            if len(data) and isinstance(data[0], dict):
                objects = [Object(i, **item)
                           for (i, item) in enumerate(data, 1)]
            else:
                objects = data
            super(DataTableBase, self).__init__(request, objects, **kwargs)

    class Meta:
        template = 'common/form-fields/data-grid/data_table.html'
        name = ''
        footer = False

    attrs = dict((col_id, cls(col_id, verbose_name=col_name, table_name=name))
                 for (col_id, cls, col_name) in columns)
    attrs['Meta'] = Meta
    return tables.base.DataTableMetaclass('DataTable', (DataTableBase,), attrs)


class TableWidget(floppyforms.widgets.Input):
    template_name = 'common/form-fields/data-grid/table_field.html'
    delimiter_re = re.compile('([\w-]*)@@([0-9]*)@@([\w-]*)')
    types = {'label': Column,
             'radio': RadioColumn,
             'checkbox': CheckColumn}

    def __init__(self, columns_spec=None, table_class=None, js_buttons=True,
                 min_value=None, max_value=None, max_sync=None,
                 *args, **kwargs):
        assert columns_spec is not None or table_class is not None
        self.columns = []
        if columns_spec:
            for spec in columns_spec:
                name = spec['column_name']
                self.columns.append((name,
                                     self.types[spec['column_type']],
                                     spec.get('title', None) or name.title()))
        self.table_class = table_class
        self.js_buttons = js_buttons
        self.min_value = min_value
        self.max_value = max_value
        self.max_sync = max_sync
        # FixME: we need to use this hack because TableField passes all kwargs
        # to TableWidget
        for kwarg in ('widget', 'description', 'description_title'):
            kwargs.pop(kwarg, None)
        super(TableWidget, self).__init__(*args, **kwargs)

    def get_context(self, name, value, attrs=None):
        ctx = super(TableWidget, self).get_context_data()
        if value:
            if self.table_class:
                cls = self.table_class
            else:
                cls = DataTableFactory(name, self.columns)
            ctx.update({
                'data_table': cls(self.request, value),
                'js_buttons': self.js_buttons,
                'min_value': self.min_value,
                'max_value': self.max_value,
                'max_sync': self.max_sync
            })
        return ctx

    def value_from_datadict(self, data, files, name):
        def extract_value(row_key, col_id, col_cls):
            if col_cls == CheckColumn:
                val = data.get("{0}@@{1}@@{2}".format(name, row_key, col_id),
                               False)
                return val and val == 'on'
            elif col_cls == RadioColumn:
                row_id = data.get("{0}@@@@{1}".format(name, col_id), False)
                return row_id == row_key
            else:
                return data.get("{0}@@{1}@@{2}".format(
                    name, row_key, col_id), None)

        def extract_keys():
            keys = set()
            regexp = re.compile('^{name}@@([^@]*)@@.*$'.format(name=name))
            for key in data.iterkeys():
                match = re.match(regexp, key)
                if match and match.group(1):
                    keys.add(match.group(1))
            return keys

        items = []
        if self.table_class:
            columns = [(_name, column.__class__, unicode(column.verbose_name))
                       for (_name, column)
                       in self.table_class.base_columns.items()]
        else:
            columns = self.columns

        for row_key in extract_keys():
            item = {}
            for column_id, column_instance, column_name in columns:
                value = extract_value(row_key, column_id, column_instance)
                item[column_id] = value
            items.append(Object(row_key, **item))

        return items

    class Media:
        css = {'all': ('muranodashboard/css/tablefield.css',)}


class TableField(CustomPropertiesField):
    def __init__(self, columns=None, label=None, table_class=None,
                 initial=None,
                 **kwargs):
        widget = TableWidget(columns, table_class, **kwargs)
        super(TableField, self).__init__(
            label=label, widget=widget, initial=initial)

    @with_request
    def update(self, request, **kwargs):
        self.widget.request = request

    def clean(self, objects):
        return [obj.as_dict() for obj in objects]


class ChoiceField(forms.ChoiceField, CustomPropertiesField):
    pass


class DomainChoiceField(ChoiceField):
    @with_request
    def update(self, request, environment_id, **kwargs):
        self.choices = [("", "Not in domain")]
        domains = api.service_list_by_type(request, environment_id,
                                           'activeDirectory')
        self.choices.extend(
            [(domain.name, domain.name) for domain in domains])


class FlavorChoiceField(ChoiceField):
    @with_request
    def update(self, request, **kwargs):
        self.choices = [(flavor.name, flavor.name) for flavor in
                        novaclient(request).flavors.list()]
        for flavor in self.choices:
            if 'medium' in flavor[1]:
                self.initial = flavor[0]
                break


class KeyPairChoiceField(ChoiceField):
    " This widget allows to select keypair for VMs "
    @with_request
    def update(self, request, **kwargs):
        self.choices = [('', _('No keypair'))]
        for keypair in novaclient(request).keypairs.list():
            self.choices.append((keypair.name, keypair.name))


class ImageChoiceField(ChoiceField):
    def __init__(self, *args, **kwargs):
        self.image_type = kwargs.pop('image_type', None)
        super(ImageChoiceField, self).__init__(*args, **kwargs)

    @with_request
    def update(self, request, **kwargs):
        image_mapping, image_choices = {}, []
        murano_images = get_murano_images(request)
        for image in murano_images:
            murano_data = image.murano_property
            title = murano_data.get('title', image.name)
            if self.image_type is not None:
                itype = murano_data.get('type')

                if not self.image_type and itype is None:
                    continue

                prefix = '{type}.'.format(type=self.image_type)
                if (not itype.startswith(prefix) and
                        not self.image_type == itype):
                    continue
            image_mapping[smart_text(title)] = image.name

        for name in sorted(image_mapping.keys()):
            image_choices.append((image_mapping[name], name))
        if image_choices:
            image_choices.insert(0, ("", _("Select Image")))
        else:
            image_choices.insert(0, ("", _("No images available")))

        self.choices = image_choices


class AZoneChoiceField(ChoiceField):
    @with_request
    def update(self, request, **kwargs):
        try:
            availability_zones = novaclient(request).availability_zones.\
                list(detailed=False)
        except:
            availability_zones = []
            exceptions.handle(request,
                              _("Unable to retrieve  availability zones."))

        az_choices = [(az.zoneName, az.zoneName)
                      for az in availability_zones if az.zoneState]
        if not az_choices:
            az_choices.insert(0, ("", _("No availability zones available")))

        self.choices = az_choices


class BooleanField(forms.BooleanField, CustomPropertiesField):
    def __init__(self, *args, **kwargs):
        if 'widget' in kwargs:
            widget = kwargs['widget']
            if isinstance(widget, type):
                widget = widget(attrs={'class': 'checkbox'})
        else:
            widget = forms.CheckboxInput(attrs={'class': 'checkbox'})
        kwargs['widget'] = widget
        super(BooleanField, self).__init__(*args, **kwargs)


# This type of field is deprecated, in future floating ip fields should be
# implemented using a regular BooleanField
# TODO(ativelkov, tsufiev): add a deprecated decorator
class FloatingIpBooleanField(BooleanField):
    pass


class ClusterIPField(CharField):
    existing_subnet = None
    network_topology = None
    router_id = None

    @staticmethod
    def make_nova_validator(request, ip_ranges):
        def perform_checking(ip):
            validate_ipv4_address(ip)
            if not all_matching_cidrs(ip, ip_ranges) and ip_ranges:
                raise forms.ValidationError(_('Specified Cluster Static IP is'
                                              ' not in valid IP range'))
            try:
                ip_info = novaclient(request).fixed_ips.get(ip)
            except exceptions.UNAUTHORIZED:
                LOG.error("Error to get information about IP address"
                          " using novaclient")
                exceptions.handle(
                    request, _("Unable to retrieve information "
                               "about fixed IP or IP is not valid."),
                    ignore=True)
            except exceptions.NOT_FOUND:
                msg = "Could not found fixed ips for ip %s" % (ip,)
                LOG.error(msg)
                exceptions.handle(
                    request, _(msg),
                    ignore=True)
            else:
                if ip_info.hostname:
                    raise forms.ValidationError(
                        _('Specified Cluster Static IP is already in use'))
        return perform_checking

    def update_network_params(self, request, environment_id):
        env = api.environment_get(request, environment_id)
        self.existing_subnet = env.networking.get('cidr')
        self.network_topology = env.networking.get('topology')

    def make_neutron_validator(self):
        def perform_checking(ip):
            validate_ipv4_address(ip)
            if not self.existing_subnet:
                raise forms.ValidationError(
                    _('Cannot get allowed subnet for the environment, '
                      'consult your admin'))
            elif not IPAddress(ip) in IPNetwork(self.existing_subnet):
                raise forms.ValidationError(
                    _('Specified IP address should belong to {0} '
                      'subnet'.format(self.existing_subnet)))

        return perform_checking

    @with_request
    def update(self, request, environment_id, **kwargs):
        self.update_network_params(request, environment_id)

        if self.network_topology == 'nova':
            try:
                network_list = novaclient(request).networks.list()
                ip_ranges = [network.cidr for network in network_list]
                ranges = ', '.join(ip_ranges)
            except StandardError:
                ip_ranges, ranges = [], ''
            if ip_ranges:
                self.help_text = _('Select IP from available range: ' + ranges)
            else:
                self.help_text = _('Specify valid fixed IP')
            self.validators = [self.make_nova_validator(request, ip_ranges)]
        elif self.network_topology in ('routed', 'manual'):
            if self.network_topology == 'manual' and self.router_id is None:
                raise muranoclient_exc.NotFound(_(
                    'Router is not found. You should create one explicitly.'))
            self.widget.attrs['placeholder'] = self.existing_subnet
            self.validators = [self.make_neutron_validator()]
        else:  # 'flat' topology
            raise NotImplementedError('Flat topology is not implemented yet')
        self.error_messages['invalid'] = validate_ipv4_address.message


class DatabaseListField(CharField):
    validate_mssql_identifier = RegexValidator(
        re.compile(r'^[a-zA-z_][a-zA-Z0-9_$#@]*$'),
        _((u'First symbol should be latin letter or underscore. Subsequent ' +
           u'symbols can be latin letter, numeric, underscore, at sign, ' +
           u'number sign or dollar sign')))

    default_error_messages = {'invalid': validate_mssql_identifier.message}

    def to_python(self, value):
        """Normalize data to a list of strings."""
        if not value:
            return []
        return [name.strip() for name in value.split(',')]

    def validate(self, value):
        """Check if value consists only of valid names."""
        super(DatabaseListField, self).validate(value)
        for db_name in value:
            self.validate_mssql_identifier(db_name)


def make_select_cls(fqn):
    class DynamicSelect(hz_forms.DynamicChoiceField, CustomPropertiesField):
        def __init__(self, *args, **kwargs):
            super(DynamicSelect, self).__init__(*args, **kwargs)
            self.widget.add_item_link = 'horizon:murano:catalog:add_many'

        @with_request
        def update(self, request, environment_id, **kwargs):
            app_id = api.app_id_by_fqn(request, fqn)
            if app_id is None:
                msg = "Application with FQN='{0}' doesn't exist"
                raise KeyError(msg.format(fqn))
            self.widget.add_item_link_args = (
                environment_id, app_id, False, True)
            self.choices = [('', _('Select Application'))]
            apps = api.service_list_by_fqn(request, environment_id, fqn)
            self.choices.extend([(app['?']['id'], app.name) for app in apps])

    return DynamicSelect
