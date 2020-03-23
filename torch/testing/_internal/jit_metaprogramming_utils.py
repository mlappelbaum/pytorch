# Torch
from torch._six import PY2
from torch.jit.annotations import BroadcastingList2, BroadcastingList3  # noqa: F401
from torch.testing._internal.common_methods_invocations import non_differentiable, create_input, \
    unpack_variables
import torch.nn.functional as F
import torch
import torch.cuda
import torch.jit
import torch.jit._logging
import torch.jit.frontend
from copy import deepcopy
import math  # noqa: F401

# Testing utils
from torch._six import inf

L = 20
M = 10
S = 5

# NB: JIT script tests for all nn functional interfaces, script mode does
# not support in_place operations yet, so no inplace operation tests added.
# removed all the deprecated functions
#
# (
#   method name,
#   input size/constructing fn,
#   args (tuple represents shape of a tensor arg),
#   test variant name(will be used at test name suffix,
#       'inplace' skips grad tests),                         // optional
#   (True, nonfusible_nodes, fusible_nodes) for autodiff     // optional
#   fn to determine if test should be skipped,               // optional
#   fn mapping output to part that should be gradcheck'ed,   // optional
#   kwargs for function,                                     // optional
# )
nn_functional_tests = [
    ('conv1d', (S, S, S), ((S, S, S),)),
    ('conv2d', (S, S, S, S), ((S, S, S, S),)),
    ('conv3d', (S, S, S, S, S), ((S, S, S, S, S),)),
    ('conv_transpose1d', (S, S, S), ((S, S, S),)),
    ('conv_transpose2d', (S, S, S, S), ((S, S, S, S),)),
    ('conv_transpose3d', (S, S, S, S, S), ((S, S, S, S, S),)),
    ('conv_tbc', (S, S, S), ((S, S, S), (S,), 2)),
    ('avg_pool1d', (S, S, S), (3,)),
    ('avg_pool2d', (S, S, S, S), (3,), '', (True,)),
    ('avg_pool3d', (S, S, S, S, S), (3,)),
    ('fractional_max_pool2d', (S, S, S, S), (3, [2, 3],)),
    ('max_pool1d', (S, S, S), (2, 1)),
    ('max_pool1d', (S, S, S), (2, 1, 1, 1, False, True), 'with_indices'),
    ('max_pool2d', (S, S, S, S), (2, 1), '', (True, 'aten::max_pool2d_with_indices')),
    ('max_pool2d', (S, S, S, S), (2, 1, 1, 1, False, True), 'with_indices', (True, 'aten::max_pool2d_with_indices')),
    ('max_pool3d', (S, S, S, S, S), (2, 1)),
    ('max_unpool1d', torch.tensor([[[2., 4]]]), (torch.tensor([[[1, 3]]]), 2, 2, 0)),
    ('max_unpool2d', torch.tensor([[[[2., 4]]]]), (torch.tensor([[[[1, 3]]]]), 2, 2, 0)),
    ('max_unpool3d', torch.tensor([[[[[2., 4]]]]]), (torch.tensor([[[[[1, 3]]]]]), 2, 2, 0)),
    ('lp_pool1d', (S, S, S), (2., 3, 2,)),
    ('lp_pool2d', (S, S, S, S), (2., 3, 2,)),
    ('adaptive_max_pool1d', (S, S, S), (5,)),
    ('adaptive_max_pool2d', (S, S, S, S), ([5, 7],)),
    ('adaptive_max_pool3d', (S, S, S, S, S), ([3, 2, 2],)),
    ('adaptive_avg_pool1d', (S, S, S), (5,), '', (True,)),
    ('adaptive_avg_pool2d', (S, S, S, S), ([5, 7],), '', (True,)),
    ('adaptive_avg_pool3d', (S, S, S, S, S), ([3, 2, 2],), '', (True,)),
    ('dropout', (S, S, S), (0.5,), '', (True,
                                        ['aten::bernoulli_',
                                         'aten::empty_like', 'aten::mul', 'aten::div'])),
    ('alpha_dropout', (S, S, S), (0.5,)),
    ('dropout2d', (S, S, S), (0.5,)),
    ('dropout3d', (S, S, S), (0.5,)),
    ('feature_alpha_dropout', (S, S, S), (0.5,)),
    ('threshold', (S, S, S), (0.1, 2.), '', (True,)),
    ('threshold', (S, S, S), (0.1, 2., True), 'inplace'),
    ('relu', (S, S, S), (), '', (True,)),
    ('relu', (S, S, S), (), 'inplace'),
    ('glu', (S - 1, S - 1, S - 1), (),),
    ('hardtanh', (S, S, S), (-0.5, 0.5),),
    ('hardtanh', (S, S, S), (-0.5, 0.5, True), 'inplace'),
    ('relu6', (S, S, S), (),),
    ('relu6', (S, S, S), (True), 'inplace'),
    ('elu', (S, S, S), (0.9,),),
    ('elu', (S, S, S), (0.9, True), 'inplace'),
    ('selu', (S, S, S), (),),
    ('selu', (S, S, S), (True), 'inplace'),
    ('celu', (S, S, S), (0.9,),),
    ('celu', (S, S, S), (0.9, True), 'inplace'),
    ('leaky_relu', (S, S, S), (0.02,),),
    ('leaky_relu', (S, S, S), (0.02,), 'inplace'),
    ('rrelu', (S, S), (0.1, 0.3, False),),
    ('rrelu', (S, S), (0.1, 0.3, False, True), 'inplace'),
    ('hardshrink', (S, S, S), (0.4,),),
    ('tanhshrink', (S, S, S), (),),
    ('softsign', (S, S, S), (),),
    ('softplus', (S, S, S), (),),
    ('softmin', (S, S, S), (0,),),
    ('softmax', (S, S, S), (0,), '', (True,)),
    ('softmax', (S, S, S), (0, 3, torch.double), 'with_all_args', (True,)),
    ('tanh', (S, S, S), (), '', (True,)),
    ('sigmoid', (S, S, S), (), '', (True,)),
    ('log_softmax', (S, S, S), (0,), '', (True,)),
    ('linear', (S, S), ((M, S),), '', (True, ['aten::t', 'aten::matmul'])),
    ('linear', (S, S), ((M, S), (M,)), 'addmm', (True, ['aten::add', 'aten::mm'])),
    ('bilinear', (S, S, S), ((S, S, M), torch.zeros(M, S, M),),),
    ('embedding', torch.tensor([[1, 2, 4, 5], [4, 3, 2, 5]]), (torch.rand(6, 3), ), '', (True,)),
    ('embedding_bag', torch.tensor([1, 2, 4, 2]), (torch.rand(5, 3), torch.tensor([0, 4]),),),
    ('batch_norm', (S, S), (non_differentiable(torch.randn(S)), non_differentiable(torch.ones(S)), ),
        '', (False, 'aten::_batch_norm_impl_index')),
    ('instance_norm', (S, S, S), (non_differentiable(torch.zeros(S)), non_differentiable(torch.ones(S))),),
    ('layer_norm', (S, S, S, S), ([5],), '',
     (False, ['aten::contiguous', 'aten::_batch_norm_impl_index'])),
    ('layer_norm', (S, S, S, S), ([5], non_differentiable(torch.rand(S)),), 'with_only_weight',
     (False, ['aten::contiguous', 'aten::_batch_norm_impl_index'])),
    ('layer_norm', (S, S, S, S), ([5], None, non_differentiable(torch.rand(S)),), 'with_only_bias',
     (False, ['aten::contiguous', 'aten::_batch_norm_impl_index'])),
    ('layer_norm', (S, S, S, S), ([5], non_differentiable(torch.rand(S)),
                                  non_differentiable(torch.rand(S))), 'with_weight_and_bias',
     (False, ['aten::contiguous', 'aten::_batch_norm_impl_index', 'aten::addcmul'])),
    ('group_norm', (S, S, S), (1, torch.rand(5),),),
    ('local_response_norm', (S, S, S), (2, ),),
    ('nll_loss', F.log_softmax(torch.randn(3, 5), dim=0), (torch.tensor([1, 0, 4]),), '', (True, 'aten::nll_loss_forward')),
    ('poisson_nll_loss', torch.rand(S, 2), (torch.rand(S, 2),),),
    ('poisson_nll_loss', torch.rand(S, 2), (torch.rand(S, 2), True, True), 'full'),
    ('kl_div', F.log_softmax(torch.randn(S, 10), 1), (F.softmax(torch.randn(S, 10), 1),),),
    ('cross_entropy', (3, S), (torch.randint(S, (3,), dtype=torch.int64),),),
    ('binary_cross_entropy_with_logits', (3,), (torch.empty(3).random_(2), ),),
    ('smooth_l1_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('l1_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('mse_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('smooth_l1_loss', (3, S), ((torch.rand(3, S)),), 'with_grad'),
    ('l1_loss', (3, S), ((torch.rand(3, S)),), 'with_grad'),
    ('mse_loss', (3, S), ((torch.rand(3, S)),), 'with_grad'),
    ('margin_ranking_loss', (3, S), ((3, S), (S,)),),
    ('hinge_embedding_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('soft_margin_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('multilabel_soft_margin_loss', (3, S), (non_differentiable(torch.rand(3, S)),),),
    ('cosine_embedding_loss', (S, S), ((S, S), non_differentiable(torch.rand(S,))),),
    ('pixel_shuffle', (1, 9, 4, 4), (3,),),
    ('affine_grid', (S, 2, 3), (torch.Size([S, 1, 7, 7]),),),
    ('pad', (3, 3, 4, 2), ([1, 1],),),
    ('pairwise_distance', (S, S), ((S, S),),),
    ('pdist', (S, S), (),),
    ('cosine_similarity', (S, S), ((S, S),),),
    ('triplet_margin_loss', (S, S), ((S, S), (S, S)),),
    ('normalize', (S, S, S), (),),
    ('unfold', (S, S, S, S), ([2, 3]),),
    ('fold', (1, 3 * 2 * 2, 12), ([4, 5], [2, 2]),),
    ('grid_sample', (S, S, S, S), (non_differentiable(torch.rand(S, S, S, 2)),),),
    ('gumbel_softmax', (S, S), (2.,), '', (True, ['aten::softmax', 'aten::add', 'aten::div'], ['aten::neg'])),
    ('gumbel_softmax', (S, S), (2., True,), 'hard', (True, ['aten::softmax', 'aten::add', 'aten::div'], ['aten::neg'])),
    ('multilabel_margin_loss', torch.tensor([[0.2, -0.2, 0.07]]), (torch.tensor([[0, 0, 1]]),),),
    ('multi_margin_loss', (S, S), (non_differentiable(torch.randint(S, (S, ), dtype=torch.int64)),
                                   1, 1., non_differentiable(torch.randn(S))),),
    ('binary_cross_entropy', torch.randn(3, 2).sigmoid(), (non_differentiable(torch.rand(3, 2)),
                                                           non_differentiable(torch.randn(3, 2))),),
    ('binary_cross_entropy', torch.randn(3, 2).sigmoid(),
        (non_differentiable(torch.rand(3, 2)),
         non_differentiable(torch.randn(3, 2)), None, None, 'mean'), 'size_average'),
    ('ctc_loss', torch.rand(S, S, S).log_softmax(2).detach().requires_grad_(),
     (torch.randint(1, S, (S, S), dtype=torch.long), torch.full((S,), S, dtype=torch.long),
      torch.randint(1, S, (S,), dtype=torch.long))),
    ('upsample', torch.randn(S, S, M, M), (None, 2.), 'with_scale'),
    ('upsample', torch.randn(S, S, M, M), (4,), 'with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 1, 3, 3), (2,), 'nearest_4d'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2.), 'nearest_4d_with_scale'),
    ('interpolate', torch.randn(S, S, M, M), (4,), 'nearest_4d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 1, 3, 3), (2,), 'area_4d'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2.), 'area_4d_with_scale'),
    ('interpolate', torch.randn(S, S, M, M), (4,), 'area_4d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 1, 3, 3), (2,), 'bilinear_4d'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2.), 'bilinear_4d_with_scale'),
    ('interpolate', torch.randn(S, S, M, M), (4,), 'bilinear_4d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 1, 3, 3), (2,), 'bicubic_4d'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2.), 'bicubic_4d_with_scale'),
    ('interpolate', torch.randn(S, S, M, M), (4,), 'bicubic_4d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 3, 3), (2,), 'nearest_3d'),
    ('interpolate', torch.randn(S, M, M), (None, 2.), 'nearest_3d_with_scale'),
    ('interpolate', torch.randn(S, M, M), (4,), 'nearest_3d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 3, 3), (2,), 'area_3d'),
    ('interpolate', torch.randn(S, M, M), (None, 2.), 'area_3d_with_scale'),
    ('interpolate', torch.randn(S, M, M), (4,), 'area_3d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 3, 3), (2,), 'linear_3d'),
    ('interpolate', torch.randn(S, M, M), (None, 2.), 'linear_3d_with_scale'),
    ('interpolate', torch.randn(S, M, M), (4,), 'linear_3d_with_size'),
    ('interpolate', torch.randn(S, M, M, M, M), (None, 2.), 'nearest_5d_with_scale'),
    ('interpolate', torch.randn(S, M, M, M, M), (4,), 'nearest_5d_with_size'),
    ('interpolate', torch.zeros(3, 3, 3).view(1, 1, 3, 3, 3), (2,), 'area_5d'),
    ('interpolate', torch.randn(S, M, M, M, M), (None, 2.), 'area_5d_with_scale'),
    ('interpolate', torch.randn(S, M, M, M, M), (4,), 'area_5d_with_size'),
    ('interpolate', torch.zeros(3, 3, 3).view(1, 1, 3, 3, 3), (2,), 'trilinear_5d'),
    ('interpolate', torch.randn(S, M, M, M, M), (None, 2.), 'trilinear_5d_with_scale'),
    ('interpolate', torch.randn(S, M, M, M, M), (4,), 'trilinear_5d_with_size'),
    ('interpolate', torch.zeros(3, 3).view(1, 1, 3, 3), (2, None, 'nearest', None, False),
     'nearest_4d_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, S, M, M), (4, None, 'nearest', None, False),
     'nearest_4d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2., 'bilinear', None, False),
     'bilinear_4d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, S, M, M), (4, None, 'bilinear', None, False),
     'bilinear_4d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, S, M, M), (None, 2., 'bicubic', None, False),
     'bicubic_4d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, S, M, M), (4, None, 'bicubic', None, False),
     'bicubic_4d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M), (None, 2., 'nearest', None, False),
     'nearest_3d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M), (4, None, 'nearest', None, False),
     'nearest_3d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M), (None, 2., 'linear', None, False),
     'linear_3d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M), (4, None, 'linear', None, False),
     'linear_3d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M, M, M), (None, 2., 'nearest', None, False),
     'nearest_5d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M, M, M), (4, None, 'nearest', None, False),
     'nearest_5d_with_size_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M, M, M), (None, 2., 'trilinear', None, False),
     'trilinear_5d_with_scale_not_recompute_scale_factor'),
    ('interpolate', torch.randn(S, M, M, M, M), (4, None, 'trilinear', None, False),
     'trilinear_5d_with_size_not_recompute_scale_factor'),
]

script_template = '''
def the_method({}):
    return {}
'''

def get_call(method_name, func_type, args, kwargs):
    kwargs_str = ', '.join([k + '=' + str(v) for k, v in kwargs.items()])
    self_arg = args[0]
    if(func_type == 'method'):
        args = args[1:]

    argument_str = ', '.join(args)
    argument_str += ', ' if len(args) and len(kwargs) else ''
    argument_str += kwargs_str

    if func_type == 'functional':
        call = 'torch.{}({})'.format(method_name, argument_str)
    elif func_type == 'method':
        call = '{}.{}({})'.format(self_arg, method_name, argument_str)
    elif func_type == 'nn_functional':
        call = 'torch.nn.functional.{}({})'.format(method_name, argument_str)
    else:
        raise 'Unsupported function type'

    return call

def get_constant(x):
    if x == inf:
        return 'float(\'inf\')' if PY2 else 'math.inf'
    if x == -inf:
        return 'float(\'-inf\')' if PY2 else '-math.inf'
    return x

def get_script_args(args):
    formals = []
    tensors = []
    actuals = []
    for arg in args:
        if isinstance(arg, torch.Tensor):
            name = 'i{}'.format(len(formals))
            formals.append(name)
            actuals.append(name)
            tensors.append(arg)
        elif isinstance(arg, str):
            actuals.append("'{}'".format(arg))
        else:
            actuals.append(str(get_constant(arg)))
    return (formals, tensors, actuals)

# create a script function from (name, func_type, output_process_fn),
# and returns the compiled function and example inputs
def gen_script_fn_and_args(method_name, func_type, *args, **kwargs):
    formals, tensors, actuals = get_script_args(args)
    call = get_call(method_name, func_type, actuals, kwargs)
    script = script_template.format(', '.join(formals), call)
    CU = torch.jit.CompilationUnit(script)
    return CU.the_method, tensors

# create a script function from (name, func_type, output_process_fn),
# returns a function takes in (args, kwargs) and runs the compiled function and
# then applies the post process fn to the outputs
def create_script_fn(self, method_name, func_type, output_process_fn):
    def script_fn(*args, **kwargs):
        fn, tensors = gen_script_fn_and_args(method_name, func_type, *args, **kwargs)
        self.assertExportImport(fn.graph, tensors)
        output = output_process_fn(fn(*tensors))
        script_fn.last_graph = fn.graph_for(*tensors)
        return output
    return script_fn


# known to be failing in script
EXCLUDE_SCRIPT = {
    'test_norm_fro_default',
    'test_norm_fro_cpu',
    'test_norm_nuc',
    'test_norm_fro',
    'test_norm_nuc_batched',

    # aten op has additional cudnn argument
    'test_nn_unfold',

    # flaky test - TODO fix
    'test_nn_ctc_loss',

    # unknown builtin op
    'test_nn_fold',

    # jit doesn't support sparse tensors.
    'test_to_sparse'
}

# generates a script function and set of example inputs 
# from a specified test in the format of nn_functional_tests
def get_nn_functional_compiled_fn_and_inputs(name, self_size, args, variant_name='', *extra_args):
    test_name = 'test_nn_' + name

    if variant_name != '':
        test_name = test_name + '_' + variant_name

    no_grad = variant_name == 'inplace'

    self_variable = create_input((self_size,))[0][0]
    kwargs = None

    # need to record this because methods can change the size (e.g. unsqueeze)
    args_variable, kwargs_variable = create_input(args)

    self_tensor = deepcopy(self_variable.data)
    args_tensor = deepcopy(unpack_variables(args_variable))

    f_args_variable = (self_variable,) + args_variable
    f_args_tensor = (self_tensor,) + args_tensor
    with torch.jit._disable_emit_hooks():
        script_fn, inputs = gen_script_fn_and_args(name, "nn_functional", *f_args_variable)
    return script_fn, inputs