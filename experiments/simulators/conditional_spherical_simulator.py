#! /usr/bin/env python

import numpy as np
from scipy.stats import norm, uniform
import itertools
import logging
from experiments.simulators.base import BaseSimulator

logger = logging.getLogger(__name__)


class ConditionalSphericalGaussianSimulator(BaseSimulator):
    def __init__(self, latent_dim=8, data_dim=9, min_width=0.1, max_width=np.pi, epsilon=0.01):
        self._latent_dim = latent_dim
        self._data_dim = data_dim
        self._minphase = 0.
        self._maxphase = 2.*np.pi
        self._minwidth = min_width
        self._maxwidth = max_width
        self._epsilon = epsilon

        assert data_dim > latent_dim
        assert epsilon > 0.
        assert 0. < min_width < max_width <= 2.0 * np.pi

    def data_dim(self):
        return self._data_dim

    def latent_dim(self):
        return self._latent_dim

    def parameter_dim(self):
        return 2

    def log_density(self, x, parameters=None):
        assert parameters is not None

        z_phi, z_eps = self._transform_x_to_z(x)
        logp = self._log_density(z_phi, z_eps, parameters=parameters)

        return logp

    def sample(self, n, parameters=None):
        assert parameters is not None

        z_phi, z_eps = self._draw_z(n, parameters=parameters)
        x = self._transform_z_to_x(z_phi, z_eps)

        return x

    def distance_from_manifold(self, x):
        z_phi, z_eps = self._transform_x_to_z(x)
        return np.sum(z_eps**2, axis=1)**0.5

    def default_parameters(self):
        return np.zeros(self.parameter_dim())

    def sample_from_prior(self, n):
        return uniform.rvs(loc=-1., scale=2., size=(n, self.parameter_dim()))

    def evaluate_log_prior(self, parameters):
        parameters = parameters.reshape((-1, self.parameter_dim()))
        return np.sum(uniform.logpdf(parameters, loc=-1., scale=2.), axis=1)

    def _parse_parameters(self, n, parameters):
        parameters = parameters.reshape(-1, 2)
        widths_ = np.empty((self._latent_dim, n))
        phases_ = np.empty((self._latent_dim, n))
        widths_[:] = self._minwidth + (0.5 + 0.5 * parameters[:, 0]) * (self._maxwidth - self._minwidth)
        phases_[:] = self._minphase + (0.5 + 0.5 * parameters[:, 1]) * (self._maxphase - self._minphase)
        widths_ = widths_.T
        phases_ = phases_.T

        return phases_, widths_

    def _draw_z(self, n, parameters):
        # Parameters
        phases_, widths_ = self._parse_parameters(n, parameters)

        # Spherical coordinates
        z_phi = np.random.normal(phases_.flatten(), widths_.flatten(), size=(n*self._latent_dim)).reshape((n, self._latent_dim))
        z_phi = np.mod(z_phi, 2.0 * np.pi)

        # Fuzzy coordinates
        z_eps = np.random.normal(0.0, self._epsilon, size=(n*(self._data_dim - self._latent_dim))).reshape((n, self._data_dim - self._latent_dim))
        return z_phi, z_eps

    def _transform_z_to_x(self, z_phi, z_eps):
        r = 1.0 + z_eps[:, 0]
        a = np.concatenate(
            (2 * np.pi * np.ones((z_phi.shape[0], 1)), z_phi), axis=1
        )  # n entries, each (2 pi, z_sub)
        sins = np.sin(a)
        sins[:, 0] = 1
        sins = np.cumprod(
            sins, axis=1
        )  # n entries, each (1, sin(z0), sin(z1), ..., sin(zk))
        coss = np.cos(a)
        coss = np.roll(coss, -1)  # n entries, each (cos(z0), cos(z1), ..., cos(zk), 1)
        exact_sphere = sins * coss  # (n, k+1)
        fuzzy_sphere = exact_sphere * r[:, np.newaxis]
        x = np.concatenate((fuzzy_sphere, z_eps[:, 1:]), axis=1)
        return x

    def _transform_x_to_z(self, x):
        z_phi = np.zeros((x.shape[0], self._latent_dim))
        for i in range(self._latent_dim):
            z_phi[:, i] = np.arccos(
                x[:, i] / np.sum(x[:, i : self._latent_dim + 1] ** 2, axis=1) ** 0.5
            )
        # Special case for last component, see https://en.wikipedia.org/wiki/N-sphere#Spherical_coordinates
        z_phi[:, self._latent_dim - 1] = np.where(
            x[:, self._latent_dim] < 0.,
            2. * np.pi - z_phi[:, self._latent_dim - 1],
            z_phi[:, self._latent_dim - 1]
        )

        r = np.sum(x[:, : self._latent_dim + 1] ** 2, axis=1) ** 0.5
        z_eps = np.copy(x[:, self._latent_dim:])
        z_eps[:, 0] = r - 1
        return z_phi, z_eps

    def _log_density(self, z_phi, z_eps, parameters):
        r = 1. + z_eps[:, 0]
        phases_, widths_ = self._parse_parameters(z_phi.shape[0], parameters)

        p_sub = 0.
        individual_shifts = [-1., 0., 1.]
        for shift in itertools.product(individual_shifts, repeat=self._latent_dim):
            p_sub += norm(loc=phases_, scale=widths_).pdf(z_phi + 2.*np.pi*np.array(shift))
        logp_sub = np.log(p_sub)
        logp_eps = np.log(norm(loc=0.0, scale=self._epsilon).pdf(z_eps))

        log_det = self._latent_dim * np.abs(r)
        log_det += np.sum(
            np.arange(self._latent_dim - 1, -1, -1)[np.newaxis, :] * np.log(np.abs(np.sin(z_phi))),
            axis=1,
        )

        logp = np.concatenate((logp_sub, logp_eps), axis=1)
        logp = np.sum(logp, axis=1) + log_det

        return logp
