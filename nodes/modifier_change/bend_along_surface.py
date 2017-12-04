# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

from math import pi, degrees, floor, ceil, copysign, sqrt
from mathutils import Vector, Matrix
import numpy as np

import bpy
from bpy.props import IntProperty, EnumProperty, BoolProperty, FloatProperty

from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import updateNode, match_long_repeat, Matrix_generate, Vector_generate, Vector_degenerate, levelsOflist
from sverchok.utils.geom import autorotate_householder, autorotate_track, autorotate_diff, diameter
from sverchok.utils.geom import LinearSpline, CubicSpline, Spline2D

all_axes = [
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0))
    ]

class SvBendAlongSurfaceNode(bpy.types.Node, SverchCustomTreeNode):
    '''Bend mesh along surface'''
    bl_idname = 'SvBendAlongSurfaceNode'
    bl_label = 'Bend object along surface'
    bl_icon = 'OUTLINER_OB_EMPTY'

    modes = [('SPL', 'Cubic', "Cubic Spline", 0),
             ('LIN', 'Linear', "Linear Interpolation", 1)]

    mode = EnumProperty(name='Mode',
        default="SPL", items=modes,
        update=updateNode)

    metrics =    [('MANHATTAN', 'Manhattan', "Manhattan distance metric", 0),
                  ('DISTANCE', 'Euclidan', "Eudlcian distance metric", 1),
                  ('POINTS', 'Points', "Points based", 2),
                  ('CHEBYSHEV', 'Chebyshev', "Chebyshev distance", 3)]

    metric = EnumProperty(name='Metric',
        description = "Knot mode",
        default="DISTANCE", items=metrics,
        update=updateNode)

    axes = [
            ("X", "X", "X axis", 1),
            ("Y", "Y", "Y axis", 2),
            ("Z", "Z", "Z axis", 3)
        ]

    orient_axis_ = EnumProperty(name = "Orientation axis",
        description = "Which axis of object to put along path",
        default = "Z",
        items = axes, update=updateNode)

    def get_axis_idx(self, letter):
        return 'XYZ'.index(letter)

    def get_orient_axis_idx(self):
        return self.get_axis_idx(self.orient_axis_)

    orient_axis = property(get_orient_axis_idx)

    autoscale = BoolProperty(name="Auto scale",
        description="Scale object along orientation axis automatically",
        default=False,
        update=updateNode)

    def sv_init(self, context):
        self.inputs.new('VerticesSocket', "Vertices")
        self.inputs.new('VerticesSocket', "Surface")
        self.outputs.new('VerticesSocket', 'Vertices')

    def draw_buttons(self, context, layout):
        layout.label("Orientation:")
        layout.prop(self, "orient_axis_", expand=True)
        layout.prop(self, "mode")
        layout.prop(self, "autoscale")

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)
        layout.prop(self, 'metric')

    def build_spline(self, surface):
        if self.mode == 'LIN':
            constructor = LinearSpline
        else:
            constructor = CubicSpline
        spline = Spline2D(surface, u_spline_constructor=constructor, metric=self.metric)
        return spline
    
    def get_other_axes(self):
        # Select U and V to be two axes except orient_axis
        if self.orient_axis_ == 'X':
            u_index, v_index = 1,2
        elif self.orient_axis_ == 'Y':
            u_index, v_index = 0,2
        else:
            u_index, v_index = 0,1
        return u_index, v_index
    
    def get_uv(self, vertices):
        """
        Translate source vertices to UV space of future spline.
        vertices must be list of list of 3-tuples.
        """
        #print("Vertices: {} of {} of {}".format(type(vertices), type(vertices[0]), type(vertices[0][0])))
        u_index, v_index = self.get_other_axes()

        # Rescale U and V coordinates to [0, 1], drop third coordinate
        us = [vertex[u_index] for col in vertices for vertex in col]
        vs = [vertex[v_index] for col in vertices for vertex in col]
        min_u = min(us)
        max_u = max(us)
        min_v = min(vs)
        max_v = max(vs)

        size_u = max_u - min_u
        size_v = max_v - min_v

        result = [[((vertex[u_index] - min_u)/size_u, (vertex[v_index] - min_v)/size_v) for vertex in col] for col in vertices]

        return size_u, size_v, result
        

    def process(self):
        if not any(socket.is_linked for socket in self.outputs):
            return
        if not self.inputs['Vertices'].is_linked:
            return

        vertices_s = self.inputs['Vertices'].sv_get()
        surfaces = self.inputs['Surface'].sv_get()
        surfaces = [surfaces]

        objects = match_long_repeat([vertices_s, surfaces])

        result_vertices = []

        for vertices, surface in zip(*objects):
            #print("Surface: {} of {} of {}".format(type(surface), type(surface[0]), type(surface[0][0])))
            spline = self.build_spline(surface)
            # uv_coords will be list of lists of 2-tuples of floats
            # number of "rows" and "columns" in uv_coords will match so of vertices.
            src_size_u, src_size_v, uv_coords = self.get_uv(vertices)
            if self.autoscale:
                u_index, v_index = self.get_other_axes()
                surface_flattened = [v for col in surface for v in col]
                scale_u = diameter(surface_flattened, u_index) / src_size_u
                scale_v = diameter(surface_flattened, v_index) / src_size_v
                scale_z = sqrt(scale_u * scale_v)
            else:
                scale_z = 1.0
            new_vertices = []
            for uv_row, vertices_row in zip(uv_coords,vertices):
                new_row = []
                for ((u, v), src_vertex) in zip(uv_row, vertices_row):
                    #print("UV: ({}, {}), SRC: {}".format(u, v, src_vertex))
                    spline_vertex = np.array(spline.eval(u, v))
                    spline_normal = np.array(spline.normal(u, v))
                    #print("Spline: M {}, N {}".format(spline_vertex, spline_normal))
                    # Coordinate of source vertex corresponding to orientation axis
                    z = src_vertex[self.orient_axis]
                    new_vertex = tuple(spline_vertex + scale_z * z * spline_normal)
                    new_row.append(new_vertex)
                new_vertices.append(new_row)
            result_vertices.append(new_vertices)

        self.outputs['Vertices'].sv_set(result_vertices)

def register():
    bpy.utils.register_class(SvBendAlongSurfaceNode)

def unregister():
    bpy.utils.unregister_class(SvBendAlongSurfaceNode)

