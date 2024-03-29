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

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from django import shortcuts

from horizon import exceptions
from horizon import tables
from horizon import messages

from muranodashboard.environments import api
from muranodashboard.environments import consts
from muranodashboard.openstack.common import timeutils
from consts import STATUS_ID_DEPLOYING
from consts import STATUS_CHOICES
from consts import STATUS_DISPLAY_CHOICES
from consts import STATUS_ID_NEW
from consts import DEPLOYMENT_STATUS_DISPLAY_CHOICES


def creation_allowed(self, request, environment):
    environment_id = self.table.kwargs['environment_id']
    env = api.environment_get(request, environment_id)
    status = getattr(env, 'status', None)

    if status not in [STATUS_ID_DEPLOYING]:
        return True
    return False


class AddApplication(tables.LinkAction):
    name = 'AddApplication'
    verbose_name = _('Add Component')
    classes = ('btn-launch',)

    def allowed(self, request, environment):
        return creation_allowed(self, request, environment)

    def get_link_url(self, datum=None):
        base_url = reverse('horizon:murano:catalog:switch_env',
                           args=(self.table.kwargs['environment_id'],))
        redirect_url = reverse('horizon:murano:catalog:index')
        return '{0}?next={1}'.format(base_url, redirect_url)


class CreateEnvironment(tables.LinkAction):
    name = 'CreateEnvironment'
    verbose_name = _('Create Environment')
    url = 'horizon:murano:environments:create_environment'
    classes = ('btn-launch', 'ajax-modal')

    def allowed(self, request, datum):
        return True

    def action(self, request, environment):
        api.environment_create(request, environment)


class DeleteEnvironment(tables.DeleteAction):
    data_type_singular = _('Environment')
    data_type_plural = _('Environments')

    def allowed(self, request, environment):
        if environment:
            environment = api.environment_get(request, environment.id)
            if environment.status == STATUS_ID_DEPLOYING:
                deployment = api.deployments_list(request, environment.id)[0]
                last_action = timeutils.parse_strtime(
                    deployment.started.replace(' ', 'T'),
                    timeutils._ISO8601_TIME_FORMAT)
                return timeutils.is_older_than(last_action, 15 * 60)
        return True

    def action(self, request, environment_id):
        api.environment_delete(request, environment_id)


class EditEnvironment(tables.LinkAction):
    name = 'edit'
    verbose_name = _('Edit Environment')
    url = 'horizon:murano:environments:update_environment'
    classes = ('ajax-modal', 'btn-edit')

    def allowed(self, request, environment):
        status = getattr(environment, 'status', None)
        if status not in [STATUS_ID_DEPLOYING]:
            return True
        else:
            return False


class DeleteService(tables.DeleteAction):
    data_type_singular = _('Component')
    data_type_plural = _('Components')

    def allowed(self, request, service=None):
        environment_id = self.table.kwargs.get('environment_id')
        env = api.environment_get(request, environment_id)
        status = getattr(env, 'status', None)

        return False if status == STATUS_ID_DEPLOYING else True

    def action(self, request, service_id):
        try:
            environment_id = self.table.kwargs.get('environment_id')
            for service in self.table.data:
                if service['?']['id'] == service_id:
                    api.service_delete(request,
                                       environment_id,
                                       service_id)
        except:
            msg = _('Sorry, you can\'t delete service right now')
            redirect = reverse("horizon:murano:environments:index")
            exceptions.handle(request, msg, redirect=redirect)


class DeployEnvironment(tables.BatchAction):
    name = 'deploy'
    action_present = _('Deploy')
    action_past = _('Deployed')
    data_type_singular = _('Environment')
    data_type_plural = _('Environment')
    classes = 'btn-launch'

    def allowed(self, request, environment):
        status = getattr(environment, 'status', None)
        if status == STATUS_ID_DEPLOYING:
            return False
        if environment.version == 0 and not environment.has_services:
            return False
        return True

    def action(self, request, environment_id):
        try:
            api.environment_deploy(request, environment_id)
        except Exception:
            msg = _('Unable to deploy. Try again later')
            redirect = reverse('horizon:murano:environments:index')
            exceptions.handle(request, msg, redirect=redirect)


class DeployThisEnvironment(tables.Action):
    name = 'deploy_env'
    verbose_name = _('Deploy This Environment')
    requires_input = False
    classes = ('btn-launch')

    def allowed(self, request, service):
        environment_id = self.table.kwargs['environment_id']
        env = api.environment_get(request, environment_id)
        status = getattr(env, 'status', None)
        version = getattr(env, 'version', None)

        if status == STATUS_ID_DEPLOYING:
            return False
        services = self.table.data
        if version == 0 and not services:
            return False
        return True

    def single(self, data_table, request, service_id):
        environment_id = data_table.kwargs['environment_id']
        try:
            api.environment_deploy(request, environment_id)
            messages.success(request, _('Deploy started'))
        except:
            msg = _('Unable to deploy. Try again later')
            exceptions.handle(
                request, msg,
                redirect=reverse('horizon:murano:environments:index'))
        return shortcuts.redirect(
            reverse('horizon:murano:environments:services',
                    args=(environment_id,)))


class ShowEnvironmentServices(tables.LinkAction):
    name = 'show'
    verbose_name = _('Components')
    url = 'horizon:murano:environments:services'

    def allowed(self, request, environment):
        return True


class UpdateEnvironmentRow(tables.Row):
    ajax = True

    def get_data(self, request, environment_id):
        return api.environment_get(request, environment_id)


class UpdateServiceRow(tables.Row):
    ajax = True

    def get_data(self, request, service_id):
        environment_id = self.table.kwargs['environment_id']
        return api.service_get(request, environment_id, service_id)


class ShowDeployments(tables.LinkAction):
    name = 'show_deployments'
    verbose_name = _('Show Deployments')
    url = 'horizon:murano:environments:deployments'

    def allowed(self, request, environment):
        return environment.status != STATUS_ID_NEW


class EnvironmentsTable(tables.DataTable):
    name = tables.Column('name',
                         link='horizon:murano:environments:services',
                         verbose_name=_('Name'))

    status = tables.Column('status',
                           verbose_name=_('Status'),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)

    class Meta:
        name = 'murano'
        verbose_name = _('Environments')
        row_class = UpdateEnvironmentRow
        status_columns = ['status']
        table_actions = (CreateEnvironment,)
        row_actions = (ShowEnvironmentServices, DeployEnvironment,
                       EditEnvironment, DeleteEnvironment, ShowDeployments)


def get_service_details_link(service):
    return reverse('horizon:murano:environments:service_details',
                   args=(service.environment_id, service['?']['id']))


def get_service_type(datum):
    return datum['?'].get(consts.DASHBOARD_ATTRS_KEY, {}).get('name')


class ServicesTable(tables.DataTable):
    name = tables.Column('name',
                         verbose_name=_('Name'),
                         link=get_service_details_link)

    _type = tables.Column(get_service_type,
                          verbose_name=_('Type'))

    status = tables.Column(lambda datum: datum['?'].get('status'),
                           verbose_name=_('Status'),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    operation = tables.Column('operation',
                              verbose_name=_('Last operation'))
    operation_updated = tables.Column('operation_updated',
                                      verbose_name=_('Time updated'))

    def get_object_id(self, datum):
        return datum['?']['id']

    class Meta:
        name = 'services'
        verbose_name = _('Components')
        status_columns = ['status']
        row_class = UpdateServiceRow
        table_actions = (AddApplication, DeleteService,
                         DeployThisEnvironment)
        row_actions = (DeleteService,)


class ShowDeploymentDetails(tables.LinkAction):
    name = 'show_deployment_details'
    verbose_name = _('Show Details')

    def get_link_url(self, deployment=None):
        kwargs = {'environment_id': deployment.environment_id,
                  'deployment_id': deployment.id}
        return reverse('horizon:murano:environments:deployment_details',
                       kwargs=kwargs)

    def allowed(self, request, environment):
        return True


class DeploymentsTable(tables.DataTable):
    started = tables.Column('started',
                            verbose_name=_('Time Started'))
    finished = tables.Column('finished',
                             verbose_name=_('Time Finished'))

    status = tables.Column('state',
                           verbose_name=_('Status'),
                           status=True,
                           display_choices=DEPLOYMENT_STATUS_DISPLAY_CHOICES)

    class Meta:
        name = 'deployments'
        verbose_name = _('Deployments')
        row_actions = (ShowDeploymentDetails,)


class EnvConfigTable(tables.DataTable):
    name = tables.Column('name',
                         verbose_name=_('Name'))
    _type = tables.Column(
        lambda datum: datum['?'][consts.DASHBOARD_ATTRS_KEY]['name'],
        verbose_name=_('Type'))

    def get_object_id(self, datum):
        return datum['?']['id']

    class Meta:
        name = 'environment_configuration'
        verbose_name = _('Deployed Components')
