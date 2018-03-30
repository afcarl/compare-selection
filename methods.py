import tempfile, os, glob

import numpy as np
import regreg.api as rr

from selection.algorithms.lasso import lasso, lasso_full
from selection.algorithms.sqrt_lasso import choose_lambda
from selection.truncated.gaussian import truncated_gaussian_old as TG
from selection.randomized.lasso import highdim

from utils import BHfilter

# Rpy

import rpy2.robjects as rpy
from rpy2.robjects import numpy2ri

methods = {}

class generic_method(object):

    q = 0.2
    method_name = 'Generic method'

    @classmethod
    def setup(cls, sigma):
        pass

    def __init__(self, X, Y, l_theory, l_min, l_1se):
        (self.X,
         self.Y,
         self.l_theory,
         self.l_min,
         self.l_1se) = (X,
                        Y,
                        l_theory,
                        l_min,
                        l_1se)

    def select(self):
        raise NotImplementedError('abstract method')

    @classmethod
    def register(cls):
        methods[cls.__name__] = cls

# Knockoff selection

class knockoffs_mf(generic_method):

    method_name = 'ModelX Knockoffs  (full)'

    def select(self):
        try:
            numpy2ri.activate()
            rpy.r.assign('X', self.X)
            rpy.r.assign('Y', self.Y)
            rpy.r.assign('q', self.q)
            rpy.r('V=knockoff.filter(X, Y, fdr=q)$selected')
            rpy.r('if (length(V) > 0) {V = V-1}')
            V = rpy.r('V')
            numpy2ri.deactivate()
            return np.asarray(V, np.int), np.asarray(V, np.int)
        except:
            return [], []

knockoffs_mf.register()

class knockoffs_sigma(generic_method):

    method_name = 'ModelX Knockoffs with Sigma, asdp, (full)'
    factor_method = 'asdp'

    @classmethod
    def setup(cls, sigma):

        numpy2ri.activate()

        # see if we've factored this before

        have_factorization = False
        factors = glob.glob('knockoff_factorizations/*%s*npz' % cls.factor_method)
        for factor in factors:
            factor = np.load(factor)
            sigma_f = factor['sigma']
            if ((sigma_f.shape == sigma.shape) and
                np.allclose(sigma_f, sigma)):
                have_factorization = True
                cls.knockoff_chol = factor['knockoff_chol']
                cls.SigmaInv_s = factor['SigmaInv_s']
                cls.diag_s = factor['diag_s']

        if not have_factorization:
            cls.knockoff_chol, cls.SigmaInv_s, cls.diag_s = factor_knockoffs(sigma, cls.factor_method)

        numpy2ri.deactivate()

    def select(self):

        numpy2ri.activate()
        rpy.r.assign('chol_k', self.knockoff_chol)
        rpy.r.assign('SigmaInv_s', self.SigmaInv_s)
        rpy.r.assign('diag_s', self.diag_s)
        rpy.r('''
        knockoffs = function(X) {
           mu = rep(0, ncol(X))
           mu_k = X # sweep(X, 2, mu, "-") %*% SigmaInv_s
           X_k = mu_k + matrix(rnorm(ncol(X) * nrow(X)), nrow(X)) %*% 
            chol_k
           return(X_k)
        }
            ''')
        numpy2ri.deactivate()

        if True: #try:
            numpy2ri.activate()
            rpy.r.assign('X', self.X)
            rpy.r.assign('Y', self.Y)
            rpy.r.assign('q', self.q)
            rpy.r('V=knockoff.filter(X, Y, fdr=q, knockoffs=knockoffs)$selected')
            rpy.r('if (length(V) > 0) {V = V-1}')
            V = rpy.r('V')
            numpy2ri.deactivate()
            return np.asarray(V, np.int), np.asarray(V, np.int)
        else: #except:
            return [], []

knockoffs_sigma.register()

def factor_knockoffs(sigma, method='asdp'):

    numpy2ri.activate()
    rpy.r.assign('Sigma', sigma)
    rpy.r.assign('method', method)
    rpy.r('''

    # Compute the Cholesky -- from create.gaussian

    diag_s = diag(switch(method, equi = create.solve_equi(Sigma), 
                  sdp = create.solve_sdp(Sigma), asdp = create.solve_asdp(Sigma)))
    if (is.null(dim(diag_s))) {
        diag_s = diag(diag_s, length(diag_s))
    }
    SigmaInv_s = solve(Sigma, diag_s)
    Sigma_k = 2 * diag_s - diag_s %*% SigmaInv_s
    chol_k = chol(Sigma_k)
    ''')
    knockoff_chol = np.asarray(rpy.r('chol_k'))
    SigmaInv_s = np.asarray(rpy.r('SigmaInv_s'))
    diag_s = np.asarray(rpy.r('diag_s'))
    np.savez('knockoff_factorizations/%s_%s.npz' % (os.path.split(tempfile.mkstemp()[1])[1], method),
             sigma=sigma,
             diag_s=diag_s,
             SigmaInv_s=SigmaInv_s,
             knockoff_chol=knockoff_chol)

    return knockoff_chol, SigmaInv_s, diag_s

class knockoffs_sigma_equi(knockoffs_sigma):

    method_name = 'ModelX Knockoffs with Sigma, equi, (full)'
    factor_method = 'equi'

knockoffs_sigma_equi.register()

class knockoffs_orig(generic_method):
    method_name = 'Candes & Barber (full)'

    def select(self):
        try:
            numpy2ri.activate()
            rpy.r.assign('X', self.X)
            rpy.r.assign('Y', self.Y)
            rpy.r.assign('q', self.q)
            rpy.r('V=knockoff.filter(X, Y, statistic=stat.glmnet_lambdadiff, fdr=q, knockoffs=create.fixed)$selected')
            rpy.r('if (length(V) > 0) {V = V-1}')
            V = rpy.r('V')
            numpy2ri.deactivate()
            V = np.asarray(V, np.int)
            return V, V
        except:
            return [], []

knockoffs_orig.register()

class knockoffs_fixed(generic_method):

    method_name = 'Knockoffs fixed (full)'

    def select(self):
        try:
            numpy2ri.activate()
            rpy.r.assign('X', self.X)
            rpy.r.assign('Y', self.Y)
            rpy.r.assign('q', self.q)
            rpy.r('V=knockoff.filter(X, Y, fdr=q, knockoffs=create.fixed)$selected')
            rpy.r('if (length(V) > 0) {V = V-1}')
            V = rpy.r('V')
            numpy2ri.deactivate()
            return np.asarray(V, np.int), np.asarray(V, np.int)
        except:
            return [], []

knockoffs_fixed.register()

# Liu, Markovic, Tibs selection

class liu_theory(generic_method):

    method_name = "Liu + theory (full)"            

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1])

    def select(self):

        X, Y, lagrange = self.X, self.Y, self.lagrange
        n, p = X.shape
        X = X / np.sqrt(n)
        L = lasso_full.gaussian(X, Y, lagrange)
        L.fit()
        if len(L.active) > 0:
            S = L.summary(compute_intervals=False)
            active_set = np.array(S['variable'])
            pvalues = np.asarray(S['pval'])

            if len(pvalues) > 0:
                selected = [active_set[i] for i in BHfilter(pvalues, q=self.q)]
            else:
                selected = []
        else:
            selected, active_set = [], []
        return selected, active_set

liu_theory.register()

class liu_aggressive(liu_theory):

    method_name = "Liu + theory, aggressive (full)"            

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)

        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

liu_aggressive.register()

class liu_CV(liu_theory):
            
    method_name = "Liu + CV (full)" 

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_min * np.ones(X.shape[1])

liu_CV.register()

class liu_1se(liu_theory):
            
    method_name = "Liu + 1SE (full)" 

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_1se * np.ones(X.shape[1])

liu_1se.register()

# Unrandomized selected

class lee_theory(generic_method):
    
    method_name = "Lee et al. + theory (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1])

    def select(self):

        X, Y, lagrange = self.X, self.Y, self.lagrange
        n, p = X.shape
        X = X / np.sqrt(n)
        L = lasso.gaussian(X, Y, lagrange)
        L.fit()
        if len(L.active) > 0:
            S = L.summary(compute_intervals=False, alternative='onesided')
            active_set = np.array(S['variable'])
            pvalues = np.asarray(S['pval'])

            if len(pvalues) > 0:
                selected = [active_set[i] for i in BHfilter(pvalues, q=self.q)]
            else:
                selected = []
        else:
            selected, active_set = [], []
        return selected, active_set

lee_theory.register()

class lee_CV(lee_theory):
    
    method_name = "Lee et al. + CV (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_min * np.ones(X.shape[1])

lee_CV.register()

class lee_1se(lee_theory):
    
    method_name = "Lee et al. + 1SE (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_1se * np.ones(X.shape[1])

lee_1se.register()

class lee_aggressive(lee_theory):
    
    method_name = "Lee et al. + theory, aggressive (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = 0.8 * l_theory * np.ones(X.shape[1])

lee_aggressive.register()

# Randomized selected

class randomized_lasso(generic_method):

    method_name = "Randomized LASSO + theory (selected)"

    randomizer_scale = 1
    ndraw = 5000
    burnin = 1000

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1])

    def select(self):
        X, Y, lagrange = self.X, self.Y, self.lagrange

        n, p = X.shape
        X = X / np.sqrt(n)

        rand_lasso = highdim.gaussian(X,
                                      Y,
                                      lagrange,
                                      randomizer_scale=self.randomizer_scale * np.std(Y))

        signs = rand_lasso.fit()
        active_set = np.nonzero(signs)[0]
        _, pvalues, _ = rand_lasso.summary(target="selected",
                                           ndraw=self.ndraw,
                                           burnin=self.burnin,
                                           compute_intervals=False)
        if len(pvalues) > 0:
            selected = [active_set[i] for i in BHfilter(pvalues, q=self.q)]
        else:
            selected = []

        return selected, active_set

class randomized_lasso_CV(randomized_lasso):

    method_name = "Randomized LASSO + CV (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_min * np.ones(X.shape[1])

class randomized_lasso_1se(randomized_lasso):

    method_name = "Randomized LASSO + 1SE (selected)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_1se * np.ones(X.shape[1])

randomized_lasso.register(), randomized_lasso_CV.register(), randomized_lasso_1se.register()

# More aggressive lambda choice

class randomized_lasso_aggressive(randomized_lasso):

    method_name = "Randomized LASSO + theory, aggressive (selected)"

    randomizer_scale = 1
    ndraw = 5000
    burnin = 1000

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

class randomized_lasso_aggressive_half(randomized_lasso):

    method_name = "Randomized LASSO + theory, aggressive, smaller noise (selected)"

    randomizer_scale = 0.5
    ndraw = 5000
    burnin = 1000

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

class randomized_lasso_aggressive_quarter(randomized_lasso):

    method_name = "Randomized LASSO + theory, aggressive, smaller noise (selected)"

    randomizer_scale = 0.25
    ndraw = 5000
    burnin = 1000

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

randomized_lasso_aggressive.register(), randomized_lasso_aggressive_half.register(), randomized_lasso_aggressive_quarter.register()

# Randomized selected smaller randomization

class randomized_lasso_half(randomized_lasso):

    method_name = "Randomized LASSO + theory, smaller noise (selected)"
    randomizer_scale = 0.5
    pass

class randomized_lasso_half_CV(randomized_lasso_CV):

    method_name = "Randomized LASSO + CV, smaller noise (selected)"
    randomizer_scale = 0.5
    pass

class randomized_lasso_half_1se(randomized_lasso_1se):

    method_name = "Randomized LASSO + 1SE, smaller noise (selected)"
    randomizer_scale = 0.5
    pass

randomized_lasso_half.register(), randomized_lasso_half_CV.register(), randomized_lasso_half_1se.register()
# Randomized sqrt selected

class randomized_sqrtlasso(generic_method):

    method_name = "Randomized SqrtLASSO, kappa=0.7, (selected)"
    randomizer_scale = 1
    kappa = 0.7
    ndraw = 5000
    burnin = 1000

    def select(self):
        X, Y = self.X, self.Y
        n, p = X.shape
        X = X / np.sqrt(n)

        lagrange = np.ones(X.shape[1]) * choose_lambda(X) * self.kappa

        rand_lasso = highdim.sqrt_lasso(X,
                                        Y,
                                        lagrange,
                                        randomizer_scale=self.randomizer_scale / np.sqrt(n))

        signs = rand_lasso.fit()
        active_set = np.nonzero(signs)[0]
        _, pvalues, _ = rand_lasso.summary(target="selected",
                                           ndraw=self.ndraw,
                                           burnin=self.burnin,
                                           compute_intervals=False)
        if len(pvalues) > 0:
            selected = [active_set[i] for i in BHfilter(pvalues, q=self.q)]
        else:
            selected = []

        return selected, active_set

class randomized_sqrtlasso_half(randomized_sqrtlasso):

    method_name = "Randomized SqrtLASSO, kappa=0.7, smaller noise (selected)"
    randomizer_scale = 0.5
    kappa = 0.7

    pass

randomized_sqrtlasso.register(), randomized_sqrtlasso_half.register()

class randomized_sqrtlasso_bigger(randomized_sqrtlasso):

    method_name = "Randomized SqrtLASSO, kappa=0.8 (selected)"
    kappa = 0.8

    pass

class randomized_sqrtlasso_bigger_half(randomized_sqrtlasso):

    method_name = "Randomized SqrtLASSO, kappa=0.8, smaller noise (selected)"
    kappa = 0.8
    randomizer_scale = 0.5
    pass

randomized_sqrtlasso_bigger.register(), randomized_sqrtlasso_bigger_half.register()

# Randomized full

class randomized_lasso_full(generic_method):

    method_name = 'Randomized LASSO + theory (full)'
    randomizer_scale = 1
    ndraw = 5000
    burnin = 1000

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1])

    def select(self):
        X, Y, lagrange = self.X, self.Y, self.lagrange
        n, p = X.shape
        X = X / np.sqrt(n)

        rand_lasso = highdim.gaussian(X,
                                      Y,
                                      lagrange,
                                      randomizer_scale=self.randomizer_scale * np.std(Y))

        signs = rand_lasso.fit()
        active_set = np.nonzero(signs)[0]
        _, pvalues, _ = rand_lasso.summary(target="full",
                                           ndraw=self.ndraw,
                                           burnin=self.burnin,
                                           compute_intervals=False)
        if len(pvalues) > 0:
            selected = [active_set[i] for i in BHfilter(pvalues, q=self.q)]
        else:
            selected = []

        return selected, active_set

class randomized_lasso_full_CV(randomized_lasso_full):

    method_name = "Randomized LASSO + CV (full)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_min * np.ones(X.shape[1])

class randomized_lasso_full_1se(randomized_lasso_full):

    method_name = "Randomized LASSO + 1SE (full)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_1se * np.ones(X.shape[1])

randomized_lasso_full.register(), randomized_lasso_full_CV.register(), randomized_lasso_full_1se.register()

# Randomized full smaller randomization

class randomized_lasso_full_half(randomized_lasso_full):

    method_name = "Randomized LASSO + theory, smaller noise (full)"
    randomizer_scale = 0.5

class randomized_lasso_full_half_CV(randomized_lasso_full_CV):

    method_name = "Randomized LASSO + CV, smaller noise (full)"
    randomizer_scale = 0.5
    pass

class randomized_lasso_full_half_1se(randomized_lasso_full_1se):

    method_name = "Randomized LASSO + 1SE, smaller noise (full)"
    randomizer_scale = 0.5
    pass

randomized_lasso_full_half.register(), randomized_lasso_full_half_CV.register(), randomized_lasso_full_half_1se.register()

# Aggressive choice of lambda

class randomized_lasso_full_aggressive(randomized_lasso_full):

    method_name = "Randomized LASSO + theory, aggressive, smaller noise (full)"

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

class randomized_lasso_full_aggressive_half(randomized_lasso_full_aggressive):

    method_name = "Randomized LASSO + theory, aggressive, smaller noise (full)"
    randomizer_scale = 0.5

    def __init__(self, X, Y, l_theory, l_min, l_1se):

        generic_method.__init__(self, X, Y, l_theory, l_min, l_1se)
        self.lagrange = l_theory * np.ones(X.shape[1]) * 0.8

randomized_lasso_full_aggressive.register(), randomized_lasso_full_aggressive_half.register()
