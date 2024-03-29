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

import logging

from django.core import urlresolvers as url
from django.utils.translation import ugettext_lazy as _  # noqa
from django.http import HttpResponse
from django.views import generic
from horizon import exceptions
from horizon import tabs
from horizon import tables
from horizon import workflows
from muranoclient.common import exceptions as exc
from muranodashboard.environments import api
from muranodashboard.environments import tabs as env_tabs
from muranodashboard.environments import tables as env_tables
from muranodashboard.environments import workflows as env_workflows


LOG = logging.getLogger(__name__)


class IndexView(tables.DataTableView):
    table_class = env_tables.EnvironmentsTable
    template_name = 'environments/index.html'

    def get_data(self):
        environments = []
        try:
            environments = api.environments_list(self.request)
        except exc.CommunicationError:
            exceptions.handle(self.request,
                              'Could not connect to Murano API \
                              Service, check connection details')
        except exc.HTTPInternalServerError:
            exceptions.handle(self.request,
                              'Murano API Service is not responding. \
                              Try again later')
        except exc.HTTPUnauthorized:
            exceptions.handle(self.request, ignore=True, escalate=True)

        return environments


class EnvironmentDetails(tabs.TabbedTableView):
    tab_group_class = env_tabs.EnvironmentDetailsTabs
    template_name = 'services/index.html'

    def get_context_data(self, **kwargs):
        context = super(EnvironmentDetails, self).get_context_data(**kwargs)

        try:
            self.environment_id = self.kwargs['environment_id']
            env = api.environment_get(self.request, self.environment_id)
            context['environment_name'] = env.name

        except:
            msg = _("Sorry, this environment doesn't exist anymore")
            redirect = url.reverse("horizon:murano:environments:index")
            exceptions.handle(self.request, msg, redirect=redirect)
        return context


class DetailServiceView(tabs.TabView):
    tab_group_class = env_tabs.ServicesTabs
    template_name = 'services/details.html'

    def get_context_data(self, **kwargs):
        context = super(DetailServiceView, self).get_context_data(**kwargs)
        context["service"] = self.get_data()
        context["service_name"] = self.service.name
        env = api.environment_get(self.request, self.environment_id)
        context["environment_name"] = env.name
        return context

    def get_data(self):
        service_id = self.kwargs['service_id']
        self.environment_id = self.kwargs['environment_id']
        try:
            self.service = api.service_get(self.request,
                                           self.environment_id,
                                           service_id)
        except exc.HTTPUnauthorized:
            exceptions.handle(self.request)

        except exc.HTTPForbidden:
            redirect = url.reverse('horizon:murano:environments:index')
            exceptions.handle(self.request,
                              _('Unable to retrieve details for '
                                'service'),
                              redirect=redirect)
        else:
            self._service = self.service
            return self._service

    def get_tabs(self, request, *args, **kwargs):
        service = self.get_data()
        return self.tab_group_class(request, service=service, **kwargs)


class CreateEnvironmentView(workflows.WorkflowView):
    workflow_class = env_workflows.CreateEnvironment
    template_name = 'environments/create.html'

    def get_initial(self):
        initial = super(CreateEnvironmentView, self).get_initial()
        initial['project_id'] = self.request.user.tenant_id
        initial['user_id'] = self.request.user.id
        return initial


class EditEnvironmentView(workflows.WorkflowView):
    workflow_class = env_workflows.UpdateEnvironment
    template_name = 'environments/update.html'
    success_url = url.reverse_lazy("horizon:murano:environments:index")

    def get_context_data(self, **kwargs):
        context = super(EditEnvironmentView, self).get_context_data(**kwargs)
        context["environment_id"] = self.kwargs['environment_id']
        return context

    def get_object(self, *args, **kwargs):
        if not hasattr(self, "_object"):
            environment_id = self.kwargs['environment_id']
            try:
                self._object = \
                    api.environment_get(self.request, environment_id)
            except:
                redirect = url.reverse("horizon:murano:environments:index")
                msg = _('Unable to retrieve environment details.')
                exceptions.handle(self.request, msg, redirect=redirect)
        return self._object

    def get_initial(self):
        initial = super(EditEnvironmentView, self).get_initial()
        initial.update({'environment_id': self.kwargs['environment_id'],
                        'name': getattr(self.get_object(), 'name', '')})
        return initial


class DeploymentsView(tables.DataTableView):
    table_class = env_tables.DeploymentsTable
    template_name = 'deployments/index.html'

    def get_context_data(self, **kwargs):
        context = super(DeploymentsView, self).get_context_data(**kwargs)

        try:
            env = api.environment_get(self.request, self.environment_id)
            context['environment_name'] = env.name
        except:
            msg = _("Sorry, this environment doesn't exist anymore")
            redirect = url.reverse("horizon:murano:environments:index")
            exceptions.handle(self.request, msg, redirect=redirect)
        return context

    def get_data(self):
        deployments = []
        self.environment_id = self.kwargs['environment_id']
        ns_url = "horizon:murano:environments:index"
        try:
            deployments = api.deployments_list(self.request,
                                               self.environment_id)

        except exc.HTTPForbidden:
            msg = _('Unable to retrieve list of deployments')
            exceptions.handle(self.request, msg, redirect=url.reverse(ns_url))

        except exc.HTTPInternalServerError:
            msg = _("Environment with id %s doesn't exist anymore"
                    % self.environment_id)
            exceptions.handle(self.request, msg, redirect=url.reverse(ns_url))
        return deployments


class DeploymentDetailsView(tabs.TabbedTableView):
    tab_group_class = env_tabs.DeploymentTabs
    table_class = env_tables.EnvConfigTable
    template_name = 'deployments/reports.html'

    def get_context_data(self, **kwargs):
        context = super(DeploymentDetailsView, self).get_context_data(**kwargs)
        context["environment_id"] = self.environment_id
        env = api.environment_get(self.request, self.environment_id)
        context["environment_name"] = env.name
        context["deployment_start_time"] = \
            api.get_deployment_start(self.request,
                                     self.environment_id,
                                     self.deployment_id)
        return context

    def get_deployment(self):
        deployment = None
        try:
            deployment = api.get_deployment_descr(self.request,
                                                  self.environment_id,
                                                  self.deployment_id)
        except (exc.HTTPInternalServerError, exc.HTTPNotFound):
            msg = _("Deployment with id %s doesn't exist anymore"
                    % self.deployment_id)
            redirect = url.reverse("horizon:murano:environments:deployments")
            exceptions.handle(self.request, msg, redirect=redirect)
        return deployment

    def get_logs(self):
        logs = []
        try:
            logs = api.deployment_reports(self.request,
                                          self.environment_id,
                                          self.deployment_id)
        except (exc.HTTPInternalServerError, exc.HTTPNotFound):
            msg = _('Deployment with id %s doesn\'t exist anymore'
                    % self.deployment_id)
            redirect = url.reverse("horizon:murano:environments:deployments")
            exceptions.handle(self.request, msg, redirect=redirect)
        return logs

    def get_tabs(self, request, *args, **kwargs):
        self.deployment_id = self.kwargs['deployment_id']
        self.environment_id = self.kwargs['environment_id']
        deployment = self.get_deployment()
        logs = self.get_logs()

        return self.tab_group_class(request, deployment=deployment, logs=logs,
                                    **kwargs)


class JSONView(generic.View):
    @staticmethod
    def get(request, **kwargs):
        data = api.load_environment_data(request, kwargs['environment_id'])
        return HttpResponse(data, content_type='application/json')
