# Author: Theo Gnassounou <theo.gnassounou@inria.fr>
#         Remi Flamary <remi.flamary@polytechnique.edu>
#         Oleksii Kachaiev <kachayev@gmail.com>
#         Ruben Bueno <ruben.bueno@polytechnique.edu>
#         Antoine Collas <contact@antoinecollas.fr>
#
# License: BSD 3-Clause


import warnings

import numpy as np
import scipy.linalg
from sklearn.decomposition import PCA
from sklearn.metrics import pairwise_distances
from sklearn.metrics.pairwise import pairwise_kernels
from sklearn.svm import SVC
from sklearn.utils import check_random_state

from ._pipeline import make_da_pipeline
from .base import BaseAdapter
from .utils import (
    check_X_domain,
    check_X_y_domain,
    extract_source_indices,
    source_target_merge,
    source_target_split,
)
from ._utils import _find_y_type, Y_Type


class SubspaceAlignmentAdapter(BaseAdapter):
    """Domain Adaptation Using Subspace Alignment.

    See [8]_ for details.

    Parameters
    ----------
    n_components : int, default=None
        The numbers of components to learn with PCA.
        If n_components is not set all components are kept::

            n_components == min(n_samples, n_features)
    random_state : int, RandomState instance or None, default=None
        Determines random number generation for dataset creation. Pass an int
        for reproducible output across multiple function calls.

    Attributes
    ----------
    `pca_source_` : object
        The PCA object fitted on the source data.
    `pca_target_` : object
        The PCA object fitted on the target data.

    References
    ----------
    .. [8] Basura Fernando et. al. Unsupervised Visual
           Domain Adaptation Using Subspace Alignment.
           In IEEE International Conference on Computer Vision, 2013.
    """

    def __init__(
        self,
        n_components=None,
        random_state=None,
    ):
        super().__init__()
        self.n_components = n_components
        self.random_state = random_state

    def adapt(self, X, y=None, sample_domain=None, **kwargs):
        """Predict adaptation (weights, sample or labels).

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        X_t : array-like, shape (n_samples, n_components)
            The data transformed to the target subspace.
        y_t : array-like, shape (n_samples,)
            The labels (same as y).
        sample_domain : array-like, shape (n_samples,)
            The domain labels transformed to the target subspace
            (same as sample_domain).
        weights : None
            No weights are returned here.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        X_source, X_target = source_target_split(X, sample_domain=sample_domain)

        if X_source.shape[0]:
            X_source = np.dot(self.pca_source_.transform(X_source), self.M_)
        if X_target.shape[0]:
            X_target = np.dot(self.pca_target_.transform(X_target), self.M_)
        # xxx(okachaiev): this could be done through a more high-level API
        X_adapt, _ = source_target_merge(
            X_source, X_target, sample_domain=sample_domain
        )
        return X_adapt

    def fit(self, X, y=None, sample_domain=None, **kwargs):
        """Fit adaptation parameters.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        self : object
            Returns self.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        X_source, X_target = source_target_split(X, sample_domain=sample_domain)

        if self.n_components is None:
            n_components = min(X.shape[0], X.shape[1])
        else:
            n_components = self.n_components
        self.random_state_ = check_random_state(self.random_state)
        self.pca_source_ = PCA(n_components, random_state=self.random_state_).fit(
            X_source
        )
        self.pca_target_ = PCA(n_components, random_state=self.random_state_).fit(
            X_target
        )
        self.n_components_ = n_components
        self.M_ = np.dot(self.pca_source_.components_, self.pca_target_.components_.T)
        return self


def SubspaceAlignment(
    base_estimator=None,
    n_components=None,
    random_state=None,
):
    """Domain Adaptation Using Subspace Alignment.

    See [8]_ for details.

    Parameters
    ----------
    base_estimator : object, default=None
        estimator used for fitting and prediction
    n_components : int, default=None
        The numbers of components to learn with PCA.
        If n_components is not set all components are kept::

            n_components == min(n_samples, n_features)
    random_state : int, RandomState instance or None, default=None
        Determines random number generation for dataset creation. Pass an int
        for reproducible output across multiple function calls.

    Returns
    -------
    pipeline : Pipeline
        A pipeline containing a SubspaceAlignmentAdapter.

    References
    ----------
    .. [8] Basura Fernando et. al. Unsupervised Visual
           Domain Adaptation Using Subspace Alignment.
           In IEEE International Conference on Computer Vision, 2013.
    """
    if base_estimator is None:
        base_estimator = SVC()

    return make_da_pipeline(
        SubspaceAlignmentAdapter(
            n_components=n_components,
            random_state=random_state,
        ),
        base_estimator,
    )


class TransferComponentAnalysisAdapter(BaseAdapter):
    """Transfer Component Analysis.

    See [9]_ for details.

    Parameters
    ----------
    kernel : kernel object, default='rbf'
        The kernel computed between data.
    n_components : int, default=None
        The numbers of components to learn with PCA.
        Should be less or equal to the number of samples
        of the source and target data.
    mu : float, default=0.1
        The parameter of the regularization in the optimization
        problem.

    Attributes
    ----------
    `X_source_` : array
        Source data used for the optimization problem.
    `X_target_` : array
        Target data used for the optimization problem.
    `K_` : array
        Kernel distance between the data (source and target).
    `eigvects_` : array
        Highest n_components eigenvectors of the solution
        of the optimization problem used to project
        in the new subspace.

    References
    ----------
    .. [9] Sinno Jialin Pan et. al. Domain Adaptation via
           Transfer Component Analysis. In IEEE Transactions
           on Neural Networks, 2011.
    """

    def __init__(self, kernel="rbf", n_components=None, mu=0.1):
        super().__init__()
        self.kernel = kernel
        self.n_components = n_components
        self.mu = mu

    def fit(self, X, y=None, sample_domain=None, **kwargs):
        """Fit adaptation parameters.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        self : object
            Returns self.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        self.X_source_, self.X_target_ = source_target_split(
            X, sample_domain=sample_domain
        )

        Kss = pairwise_kernels(self.X_source_, metric=self.kernel)
        Ktt = pairwise_kernels(self.X_target_, metric=self.kernel)
        Kst = pairwise_kernels(self.X_source_, self.X_target_, metric=self.kernel)
        K = np.block([[Kss, Kst], [Kst.T, Ktt]])
        self.K_ = K

        ns = self.X_source_.shape[0]
        nt = self.X_target_.shape[0]
        Lss = 1 / ns**2 * np.ones((ns, ns))
        Ltt = 1 / nt**2 * np.ones((nt, nt))
        Lst = -1 / (ns * nt) * np.ones((ns, nt))
        L = np.block([[Lss, Lst], [Lst.T, Ltt]])

        H = np.eye(ns + nt) - 1 / (ns + nt) * np.ones((ns + nt, ns + nt))

        A = np.eye(ns + nt) + self.mu * K @ L @ K
        B = K @ H @ K
        solution = np.linalg.solve(A, B)

        eigvals, eigvects = np.linalg.eigh(solution)

        if self.n_components is None:
            n_components = min(X.shape[0], X.shape[1])
        else:
            n_components = self.n_components
        selected_components = np.argsort(np.abs(eigvals))[::-1][:n_components]
        self.eigvects_ = np.real(eigvects[:, selected_components])
        return self

    def adapt(self, X, y=None, sample_domain=None, **kwargs):
        """Predict adaptation (weights, sample or labels).

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        X_t : array-like, shape (n_samples, n_components)
            The data transformed to the target subspace.
        sample_domain : array-like, shape (n_samples,)
            The domain labels transformed to the target subspace
            (same as sample_domain).
        weights : None
            No weights are returned here.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        X_source, X_target = source_target_split(X, sample_domain=sample_domain)

        if np.array_equal(X_source, self.X_source_) and np.array_equal(
            X_target, self.X_target_
        ):
            X_ = (self.K_ @ self.eigvects_)[: X.shape[0]]
        else:
            Ks = pairwise_kernels(X, self.X_source_, metric=self.kernel)
            Kt = pairwise_kernels(X, self.X_target_, metric=self.kernel)
            K = np.concatenate((Ks, Kt), axis=1)
            X_ = (K @ self.eigvects_)[: X.shape[0]]
        return X_


def TransferComponentAnalysis(
    base_estimator=None, kernel="rbf", n_components=None, mu=0.1
):
    """Domain Adaptation Using Transfer Component Analysis.

    See [9]_ for details.

    Parameters
    ----------
    base_estimator : object, default=None
        estimator used for fitting and prediction
    kernel : kernel object, default='rbf'
        The kernel computed between data.
    n_components : int, default=None
        The numbers of components to learn with PCA.
        Should be less or equal to the number of samples
        of the source and target data.
    mu : float, default=0.1
        The parameter of the regularization in the optimization
        problem.

    Returns
    -------
    pipeline : Pipeline
        A pipeline containing a TransferComponentAnalysisAdapter.

    References
    ----------
    .. [9] Sinno Jialin Pan et. al. Domain Adaptation via
           Transfer Component Analysis. In IEEE Transactions
           on Neural Networks, 2011.
    """
    if base_estimator is None:
        base_estimator = SVC()

    return make_da_pipeline(
        TransferComponentAnalysisAdapter(
            kernel=kernel, n_components=n_components, mu=mu
        ),
        base_estimator,
    )


class TransferJointMatchingAdapter(BaseAdapter):
    """Domain Adaptation Using TJM: Transfer Joint Matching.

    See [26]_ for details.

    Parameters
    ----------
    n_components : int, default=None
        The numbers of components to learn with PCA.
        Should be less or equal to the number of samples
        of the source and target data.
    tradeoff : float, default=1e-2
        The tradeoff constant for the TJM algorithm.
        It serves to trade off feature matching and instance
        reweighting.
    max_iter : int>0, default=100
        The maximal number of iteration before stopping when
        fitting.
    kernel : kernel object, default='rbf'
        The kernel computed between data.
    tol : float, default=0.01
        The threshold for the differences between losses on two iteration
        before the algorithm stops
    verbose : bool, default=False
        If True, print the loss value at each iteration.

    Attributes
    ----------
    None

    References
    ----------
    .. [26]  [Long et al., 2014] Long, M., Wang, J., Ding, G., Sun, J., and Yu, P.
             (2014). Transfer joint matching for unsupervised domain adaptation.
             In IEEE Conference on Computer Vision and Pattern Recognition (CVPR),
             pages 1410–1417

    """

    def __init__(
        self,
        n_components=None,
        tradeoff=1e-2,
        max_iter=100,
        kernel="rbf",
        tol=0.01,
        verbose=False,
    ):
        super().__init__()
        self.n_components = n_components
        self.tradeoff = tradeoff
        self.kernel = kernel
        self.max_iter = max_iter
        self.tol = tol
        self.verbose = verbose

    def adapt(self, X, y=None, sample_domain=None, **kwargs):
        """Predict adaptation (weights, sample or labels).

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        X_t : array-like, shape (n_samples, n_components)
            The data transformed to the target subspace.
        y_t : array-like, shape (n_samples,)
            The labels (same as y).
        sample_domain : array-like, shape (n_samples,)
            The domain labels transformed to the target subspace
            (same as sample_domain).
        weights : None
            No weights are returned here.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        X_source, X_target = source_target_split(X, sample_domain=sample_domain)

        if np.array_equal(X_source, self.X_source_) and np.array_equal(
            X_target, self.X_target_
        ):
            K = self._get_kernel_matrix(X_source, X_target)
            X_ = K @ self.A_
        else:
            Ks = pairwise_kernels(X, self.X_source_, metric=self.kernel)
            Kt = pairwise_kernels(X, self.X_target_, metric=self.kernel)
            K = np.concatenate((Ks, Kt), axis=1)
            X_ = K @ self.A_
        return X_

    def _get_mmd_matrix(self, ns, nt, sample_domain):
        Mss = (1 / (ns**2)) * np.ones((ns, ns))
        Mtt = (1 / (nt**2)) * np.ones((nt, nt))
        Mst = -(1 / (ns * nt)) * np.ones((ns, nt))
        M = np.block([[Mss, Mst], [Mst.T, Mtt]])
        return M

    def _get_kernel_matrix(self, X_source, X_target):
        Kss = pairwise_kernels(X_source, metric=self.kernel)
        Ktt = pairwise_kernels(X_target, metric=self.kernel)
        Kst = pairwise_kernels(X_source, X_target, metric=self.kernel)
        K = np.block([[Kss, Kst], [Kst.T, Ktt]])
        return K

    def fit(self, X, y=None, sample_domain=None, **kwargs):
        """Fit adaptation parameters.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            The source data.
        y : array-like, shape (n_samples,)
            The source labels.
        sample_domain : array-like, shape (n_samples,)
            The domain labels (same as sample_domain).

        Returns
        -------
        self : object
            Returns self.
        """
        X, sample_domain = check_X_domain(
            X,
            sample_domain,
            allow_multi_source=True,
            allow_multi_target=True,
        )
        X_source, X_target = source_target_split(X, sample_domain=sample_domain)

        if self.n_components is None:
            n_components = min(X.shape[0], X.shape[1])
        else:
            n_components = self.n_components
        self.X_source_ = X_source
        self.X_target_ = X_target

        n = X.shape[0]
        source_mask = extract_source_indices(sample_domain)

        H = np.identity(n) - 1 / n * np.ones((n, n))
        K = self._get_kernel_matrix(X_source, X_target)
        M = self._get_mmd_matrix(X_source.shape[0], X_target.shape[0], sample_domain)
        M /= np.linalg.norm(M, ord="fro")
        G = np.identity(n)

        EPS_eigval = 1e-10
        last_loss = -2 * self.tol
        for i in range(self.max_iter):
            # update A
            B = K @ M @ K.T + self.tradeoff * G
            C = K @ H @ K.T
            B = B + EPS_eigval * np.identity(n)
            C = C + EPS_eigval * np.identity(n)
            phi, A = scipy.linalg.eigh(B, C)
            phi = phi + EPS_eigval
            indices = np.argsort(phi)[:n_components]
            phi, A = phi[indices], A[:, indices]
            error_eigv = np.linalg.norm(B @ A - C @ A @ np.diag(phi))
            if error_eigv > 1e-5:
                warnings.warn(
                    "The solution of the generalized eigenvalue problem "
                    "is not accurate."
                )

            # update G
            A_norms = np.linalg.norm(A, axis=1)
            G = np.zeros(n, dtype=np.float64)
            G[A_norms != 0] = 1 / (2 * A_norms[A_norms != 0] + EPS_eigval)
            G[~source_mask] = 1
            G = np.diag(G)

            loss = np.trace(A.T @ K @ M @ K @ A)
            reg = (
                np.sum(np.linalg.norm(A[source_mask], axis=1))
                + np.linalg.norm(A[~source_mask]) ** 2
            )
            loss_total = loss + self.tradeoff * reg
            # print objective function and constraint satisfaction
            if self.verbose:
                print(
                    f"iter {i}: loss={loss_total:.3e}, loss_mmd={loss:.3e}, "
                    f"reg={reg:.3e}"
                )
                mat = A.T @ K @ H @ K.T @ A
                cond = np.allclose(mat, np.identity(n_components))
                dist = np.linalg.norm(mat - np.identity(n_components))
                print(f"Constraint satisfaction: {cond}, dist={dist:.3e}")
                print(f"Error of generalized eigendecomposition: {error_eigv:.3e}")

            if last_loss == 0 or np.abs(last_loss - loss_total) / last_loss < self.tol:
                break
            else:
                last_loss = loss_total

        self.A_ = A

        return self


def TransferJointMatching(
    base_estimator=None,
    n_components=None,
    tradeoff=1e-2,
    kernel="rbf",
    max_iter=100,
    tol=0.01,
):
    """

    Parameters
    ----------
    base_estimator : object, default=None
        estimator used for fitting and prediction
    n_components : int, default=None
        The numbers of components to learn with PCA.
        Should be less or equal to the number of samples
        of the source and target data.
    tradeoff : float, default=1e-2
        The tradeoff constant for the TJM algorithm.
        It serves to trade off feature matching and instance
        reweighting.
    max_iter : int>0, default=100
        The maximal number of iteration before stopping when
        fitting.
    kernel : kernel object, default='rbf'
        The kernel computed between data.
    tol :

    Returns
    -------
    pipeline : Pipeline
        A pipeline containing a TransferJointMatchingAdapter.

    References
    ----------
    .. [26]  [Long et al., 2014] Long, M., Wang, J., Ding, G., Sun, J., and Yu, P.
             (2014). Transfer joint matching for unsupervised domain adaptation.
             In IEEE Conference on Computer Vision and Pattern Recognition (CVPR),
             pages 1410–1417
    """
    if base_estimator is None:
        base_estimator = SVC()

    return make_da_pipeline(
        TransferJointMatchingAdapter(
            tradeoff=tradeoff,
            n_components=n_components,
            kernel=kernel,
            max_iter=max_iter,
            tol=tol,
        ),
        base_estimator,
    )

# Call it instead CTCAdapter ?
class ConditionalTransferableComponentsAdapter(BaseAdapter):
    def __init__(
        self,
        gamma,
        eps = 1e-3,
        lmbd=1e-3,
        lmbd_s=1e-3,
        lmbd_l=1e-4,
        max_iter=100
    ):
        super().__init__()
        self.gamma = gamma
        self.eps = eps
        self.lmbd = lmbd
        self.lmbd_s = lmbd_s
        self.lmbd_l = lmbd_l
        self.max_iter = max_iter
        self.max_iter = max_iter


    

    def _mapping_optimization(self, X_source, X_target, y_source, d):
        """Weight optimization"""
        try:
            import torch
        except ImportError:
            raise ImportError(
                "ConditionalTransferableComponentsAdapter requires pytorch to be installed."
            )
        n_s, n_t = X_source.shape[0], X_target.shape[0]

        # We estimate the parameters α, W , G, and H by minimizing J_ct
         
        # check y is discrete or continuous
        self.discrete_ = _find_y_type(y_source) == Y_Type.DISCRETE

        def compute_Beta_A_B(discrete, alpha, G, H):
            if discrete:
                classes = np.unique(y_source)
                n_c = len(classes)

                R = np.zeros((X_source.shape[0], len(classes)))
                for i, c in enumerate(classes):
                    R[:, i] = (n_s/n_c)*(y_source == c).astype(int)

                Beta = R*alpha
                A = (R@G).T
                B = (R@H).T
            else:
            #TODO
                pass

            return Beta, A, B

        
        def func(alpha, W, G, H):
            Beta, A, B = compute_Beta_A_B(self.discrete_, alpha, G, H)
            X_ct = A * (W.T @ X_source) + B

            K_s = pairwise_kernels(X_ct, metric="rbf", gamma=self.gamma)
            K_t = pairwise_kernels(W.T @ X_target, metric="rbf", gamma=self.gamma)
            K_t_s = pairwise_kernels(W.T@X_target, X_ct, metric="rbf", gamma=self.gamma)

            L = pairwise_kernels(y_source, metric="rbf", gamma=self.gamma)

            J_ct = ((1/n_s**2)*Beta.T @ K_s @ Beta -
                (2/n_s*n_t)*np.ones((n_s+n_t)).T @ K_t_s @ Beta +
                (1/n_t**2)*np.ones((n_t)).T @ K_t @ np.ones((n_t))
            )

            Jreg = ((self.lmbd_s/n_s) * np.linalg.norm(A - np.np.ones((d, n_s)), ord=2) +
                (self.lmbd_l/n_s) * np.linalg.norm(B, ord=2)
            )

            J_ct_con = J_ct + self.lmbd * np.trace(L@np.linalg.inv(K_s + n_s*self.eps*np.eye(n_s))) + Jreg

            return J_ct_con

        #####
        alpha = torch.ones(n_s, dtype=torch.float64, requires_grad=True)
        W = torch.ones(d, n_s, dtype=torch.float64, requires_grad=True)
        G = torch.ones((n_s, n_s), dtype=torch.float64, requires_grad=True)
        H = torch.zeros((n_t, n_s), dtype=torch.float64, requires_grad=True)

        #TODO: Use the torch_minimize function from PR # 103 and adapt it
        # to accept multiple variables

        #TODO: Add constraints on alpha, W, G, H
        for i in range(self.max_iter):
            if i % 3 == 0:
                # For α, we use quadratic programming (QP) to minimize
                # Jˆct w.r.t. α under constraint (11)
                #TODO: Switch to qp_solver here
                alpha, _ = torch_minimize(func, alpha, args=(G, H, W), tol=self.tol, max_iter=1)
            elif i % 3 == 1:
                W, _ = torch_minimize(func, W, args=(alpha, G, H) tol=self.tol, max_iter=1)
            else:
                (G, H), _ = torch_minimize(func, (G, H), args=(alpha, W), tol=self.tol, max_iter=1)

        return alpha, W, G, H

    def fit(self, X, y=None, sample_domain=None, **kwargs):
        X, y, sample_domain = check_X_y_domain(X, y, sample_domain)
        X_source, X_target, y_source, _ = source_target_split(
            X, y, sample_domain=sample_domain
        )
        self.X_source_ = X_source

        self.alpha_, self.W_, self.G_, self.H_ = self._mapping_optimization(
            X_source, X_target, y_source)
    
    def adapt(self, X, y=None, sample_domain=None, **kwargs):
        X, sample_domain = check_X_domain(
            X,
            sample_domain
        )

        n_s = X_source.shape[0]

        source_idx = extract_source_indices(sample_domain)
        X_source, X_target = X[source_idx], X[~source_idx]

        if source_idx.sum() > 0:
            if np.array_equal(self.X_source_, X[source_idx]):
                W, G, H = self.W_, self.G_, self.H_
            else:
                if self.discrete_:
                    # recompute the mapping
                    X, y, sample_domain = check_X_y_domain(X, y, sample_domain)
                    source_idx = extract_source_indices(sample_domain)
                    y_source = y[source_idx]
                    classes = self.classes_
                    n_c = len(classes)
                    R = np.zeros((X_source.shape[0], len(classes)))
                    for i, c in enumerate(classes):
                        R[:, i] = (y_source == c).astype(int)

                    W = R @ self.W_
                    A = (n_s/n_c)*(R@self.G_).T
                    B = (n_s/n_c)*(R@self.H_).T
                else:
                    # assign the nearest neighbor's mapping to the source samples
                    C = pairwise_distances(X[source_idx], self.X_source_)
                    idx = np.argmin(C, axis=1)

                    W = C[idx] @ self.W_[idx]
                    A = (n_s/n_c)*(C[idx]@self.G_[idx]).T
                    B = (n_s/n_c)*(C[idx]@self.H_[idx]).T
            X_source_adapt = A*(W.T @ X_source) + B
            X_adapt, _ = source_target_merge(
                X_source_adapt, X_target, sample_domain=sample_domain
            )
        else:
            X_adapt = X

        return X_adapt
