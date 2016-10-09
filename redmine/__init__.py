"""
Provides public API.
"""

import os
import json

from distutils.version import LooseVersion

from . import managers, exceptions
from .packages import requests
from .version import __version__


class Redmine(object):
    """
    Entry point for all requests.
    """
    def __init__(self, url, **kwargs):
        """
        :param string url: (required). Redmine location.
        :param string key: (optional). API key used for authentication.
        :param string version: (optional). Redmine version.
        :param string username: (optional). Username used for authentication.
        :param string password: (optional). Password used for authentication.
        :param dict requests: (optional). Connection options.
        :param string impersonate: (optional). Username to impersonate.
        :param string date_format: (optional). Formatting directives for date format.
        :param string datetime_format: (optional). Formatting directives for datetime format.
        :param raise_attr_exception: (optional). Control over resource attribute access exception raising.
        :type raise_attr_exception: bool or tuple
        :param resource_paths: (optional). Paths to modules which contain additional resources.
        :type resource_paths: list or tuple
        """
        self.url = url.rstrip('/')
        self.key = kwargs.get('key', None)
        self.ver = kwargs.get('version', None)
        self.username = kwargs.get('username', None)
        self.password = kwargs.get('password', None)
        self.requests = kwargs.get('requests', {})
        self.impersonate = kwargs.get('impersonate', None)
        self.date_format = kwargs.get('date_format', '%Y-%m-%d')
        self.datetime_format = kwargs.get('datetime_format', '%Y-%m-%dT%H:%M:%SZ')
        self.raise_attr_exception = kwargs.get('raise_attr_exception', True)
        self.resource_paths = kwargs.get('resource_paths', None)

    def __getattr__(self, resource_name):
        """
        Returns either ResourceSet or Resource object depending on the method used on the ResourceManager.

        :param string resource_name: (required). Resource name.
        """
        if resource_name.startswith('_'):
            raise AttributeError

        return managers.ResourceManager(self, resource_name)

    def upload(self, filepath):
        """
        Uploads file from filepath to Redmine and returns an assigned token.

        :param string filepath: (required). Path to the file that will be uploaded.
        """
        if self.ver is not None and LooseVersion(str(self.ver)) < LooseVersion('1.4.0'):
            raise exceptions.VersionMismatchError('File uploading')

        try:
            with open(filepath, 'rb') as stream:
                url = '{0}/uploads.json'.format(self.url)
                response = self.request('post', url, data=stream, headers={'Content-Type': 'application/octet-stream'})
        except IOError:
            raise exceptions.NoFileError

        return response['upload']['token']

    def download(self, url, savepath=None, filename=None, params=None):
        """
        Downloads file from Redmine and saves it to savepath or returns it as bytes.

        :param string url: (required). URL of the file that will be downloaded.
        :param string savepath: (optional). Path where to save the file.
        :param string filename: (optional). Name that will be used for the file.
        :param dict params: (optional). Params to send in the query string.
        """
        response = self.request('get', url, params=dict(params or {}, **{'stream': True}), raw_response=True)

        # If a savepath wasn't provided we return a response directly
        # so a user can have maximum control over response data
        if savepath is None:
            return response

        try:
            from urlparse import urlsplit
        except ImportError:
            from urllib.parse import urlsplit

        if filename is None:
            filename = urlsplit(url)[2].split('/')[-1]

            if not filename:
                raise exceptions.FileUrlError

        savepath = os.path.join(savepath, filename)

        with open(savepath, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)

        return savepath

    def auth(self):
        """
        Shortcut for the case if we just want to check if user provided valid auth credentials.
        """
        return self.user.get('current')

    def request(self, method, url, headers=None, params=None, data=None, raw_response=False):
        """
        Makes requests to Redmine and returns result.

        :param string method: (required). HTTP method used for the request.
        :param string url: (required). URL of the request.
        :param dict headers: (optional). HTTP headers to send with the request.
        :param dict params: (optional). Params to send in the query string.
        :param data: (optional). Data to send in the body of the request.
        :type data: dict, bytes or file-like object
        :param bool raw_response: (optional). Whether to return raw or json encoded result.
        """
        kwargs = dict(self.requests, **{
            'headers': headers or {},
            'params': params or {},
            'data': data or {},
        })

        if 'Content-Type' not in kwargs['headers'] and method in ('post', 'put'):
            kwargs['data'] = json.dumps(data)
            kwargs['headers']['Content-Type'] = 'application/json'

        if self.impersonate is not None:
            kwargs['headers']['X-Redmine-Switch-User'] = self.impersonate

        # We would like to be authenticated by API key by default
        if 'key' not in kwargs['params'] and self.key is not None:
            kwargs['params']['key'] = self.key
        else:
            kwargs['auth'] = (self.username, self.password)

        response = getattr(requests, method)(url, **kwargs)

        if response.status_code in (200, 201):
            if raw_response:
                return response
            elif not response.content.strip():
                return True
            else:
                try:
                    return response.json()
                except (ValueError, TypeError):
                    raise exceptions.JSONDecodeError(response)
        elif response.status_code == 401:
            raise exceptions.AuthError
        elif response.status_code == 403:
            raise exceptions.ForbiddenError
        elif response.status_code == 404:
            raise exceptions.ResourceNotFoundError
        elif response.status_code == 409:
            raise exceptions.ConflictError
        elif response.status_code == 412 and self.impersonate is not None:
            raise exceptions.ImpersonateError
        elif response.status_code == 413:
            raise exceptions.RequestEntityTooLargeError
        elif response.status_code == 422:
            errors = response.json()['errors']
            raise exceptions.ValidationError(', '.join(': '.join(e) if isinstance(e, list) else e for e in errors))
        elif response.status_code == 500:
            raise exceptions.ServerError

        raise exceptions.UnknownError(response.status_code)
