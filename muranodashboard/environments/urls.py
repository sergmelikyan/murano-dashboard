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

from django.conf.urls import patterns, url

from views import IndexView, DeploymentDetailsView
from views import JSONView, EnvironmentDetails
from views import CreateEnvironmentView
from views import DetailServiceView
from views import DeploymentsView
from views import EditEnvironmentView
from openstack_dashboard.dashboards.project.instances.views import DetailView

VIEW_MOD = 'muranodashboard.environments.views'
ENVIRONMENT_ID = r'^(?P<environment_id>[^/]+)'


urlpatterns = patterns(
    VIEW_MOD,
    url(r'^environments$', IndexView.as_view(), name='index'),

    url(r'^create_environment$', CreateEnvironmentView.as_view(),
        name='create_environment'),

    url(ENVIRONMENT_ID + r'/update_environment$',
        EditEnvironmentView.as_view(),
        name='update_environment'),

    url(ENVIRONMENT_ID + r'/services$', EnvironmentDetails.as_view(),
        name='services'),

    url(ENVIRONMENT_ID + r'/services/get_d3_data$',
        JSONView.as_view(), name='d3_data'),

    url(ENVIRONMENT_ID + r'/(?P<service_id>[^/]+)/$',
        DetailServiceView.as_view(),
        name='service_details'),

    url(r'^(?P<instance_id>[^/]+)/$', DetailView.as_view(), name='detail'),

    url(ENVIRONMENT_ID + r'/deployments$',
        DeploymentsView.as_view(), name='deployments'),

    url(ENVIRONMENT_ID + r'/deployments/(?P<deployment_id>[^/]+)$',
        DeploymentDetailsView.as_view(), name='deployment_details'),
)
