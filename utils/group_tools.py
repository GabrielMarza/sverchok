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

import json
import os
import re
import zipfile
import traceback

from os.path import basename
from os.path import dirname
from itertools import chain

from .sv_IO_panel import create_dict_of_tree, import_tree

import bpy
from bpy.types import EnumProperty
from bpy.props import StringProperty
from bpy.props import BoolProperty


class SvNodeGroupCreator(bpy.types.Operator):

    '''Create a Node group from selected'''

    bl_idname = "node.sv_group_creator"
    bl_label = "Create node group"

    def execute(self, context):
        
        ng = context.space_data.node_tree
        ng.freeze(hard=True)
        # collect data
        nodes = {n for n in ng.nodes if n.select}
        if not nodes:
            self.report({"CANCELLED"}, "No nodes selected")
            return {'CANCELLED'}
        test_in = lambda l: bool(l.to_node in nodes) and bool(l.from_node not in nodes) 
        test_out = lambda l: bool(l.from_node in nodes) and bool(l.to_node not in nodes)
        out_links = [l for l in ng.links if test_out(l)]
        in_links = [l for l in ng.links if test_in(l)]
        locx = [n.location.x for n in nodes]
        locy = sum(n.location.y for n in nodes)/len(nodes)
        
        # crete node_group
        
        group_in = ng.nodes.new("SvGroupInputsNode")
        group_in.location = (min(locx)-300, locy)
        group_out = ng.nodes.new("SvGroupOutputsNode")
        group_out.location = (max(locx)+300, locy)
        group_node = ng.nodes.new("SvGroupNode")
        group_node.location = (sum(locx)/len(nodes), locy)

        for i,l in enumerate(in_links):
            out_socket = l.from_socket
            in_socket = l.to_socket
            s_name = "{}:{}".format(i,in_socket.name)
            gn_socket = group_node.inputs.new(in_socket.bl_idname, s_name )
            gi_socket = group_in.outputs.new(in_socket.bl_idname, s_name)
            
            ng.links.remove(l)
            ng.links.new(in_socket, gi_socket)
            ng.links.new(gn_socket, out_socket)
        
        for i,l in enumerate(out_links):
            out_socket = l.from_socket
            in_socket = l.to_socket
            s_name = "{}:{}".format(i, in_socket.name)
            gn_socket = group_node.outputs.new(out_socket.bl_idname, s_name)
            go_socket = group_out.inputs.new(out_socket.bl_idname, s_name)
            ng.links.remove(l)
            ng.links.new(in_socket, gn_socket)
            ng.links.new(go_socket, out_socket)
        
        group_in.collect()
        group_out.collect()
        # deselect all
        for n in ng.nodes:
            n.select = False
        nodes.add(group_in)
        nodes.add(group_out)
        # select nodes to move
        for n in nodes:
            n.select = True
        
        nodes_json = create_dict_of_tree(ng, {}, selected=True)
        print(nodes_json)
        for n in nodes:
            ng.nodes.remove(n)
        ng.unfreeze()
        group_ng = bpy.data.node_groups.new("SvGroup", 'SverchGroupTreeType')
        
        group_node.group_name = group_ng.name
        import_tree(group_ng, "", nodes_json)
        # set new node tree to active
        #context.space_data.node_tree = group_ng
        self.report({"INFO"}, "Node group created")
        return {'FINISHED'}

class SvNodeGroupEdit(bpy.types.Operator):  
    bl_idname = "node.sv_node_group_edit"
    bl_label = "Edit group"
    
    group_name = StringProperty()
    
    def execute(self, context):
        ng = context.space_data.node_tree
        node = context.node
        group_ng = bpy.data.node_groups.get(self.group_name)
        ng.freeze()
        frame = ng.nodes.new("NodeFrame")
        frame.label = group_ng.name
        for n in ng.nodes:
            n.select = False
        nodes_json = create_dict_of_tree(group_ng)
        import_tree(ng, "", nodes_json)
        nodes = [n for n in ng.nodes if n.select]
        locs = [n.location for n in nodes]
        for n in nodes:
            n.parent = frame
        ng[frame.name] = self.group_name
        ng["Group Node"] = node.name
        return {'FINISHED'}

class SvNodeGroupEditDone(bpy.types.Operator):  
    bl_idname = "node.sv_node_group_done"
    bl_label = "Save group"
    
    frame_name = StringProperty()
    
    def execute(self, context):
        ng = context.space_data.node_tree
        frame = ng.nodes.get(self.frame_name)
        if not frame:
            return {'CANCELLED'}
        nodes = [n for n in ng.nodes if n.parent == frame]
        
        g_node = ng.nodes[ng["Group Node"]]
        
        for n in ng.nodes:
            n.select = False
        for n in nodes:
            n.select = True
        in_out = [n for n in nodes if n.bl_idname in {'SvGroupInputsNode', 'SvGroupOutputsNode'}]
        
        in_out.sort(key=lambda n:n.bl_idname)
        for n in in_out:
            n.collect()
        g_node.adjust_sockets(in_out)
            
        frame.select = True
        group_ng = bpy.data.node_groups[ng[frame.name]]
        del ng[frame.name]
        group_ng.name = frame.label
        
        ng.freeze(hard=True)
        ng.nodes.remove(frame)
        nodes_json = create_dict_of_tree(ng, {}, selected=True)
        for n in nodes:
            ng.nodes.remove(n)
        g_node.group_name = group_ng.name
        ng.unfreeze(hard=True)
        group_ng.nodes.clear()
        import_tree(group_ng, "", nodes_json)
        
        self.report({"INFO"}, "Node group created")
        return {'FINISHED'}


class SverchokGroupLayoutsMenu(bpy.types.Panel):
    bl_idname = "Sverchok_groups_menu"
    bl_label = "SV Groups"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Sverchok'
    bl_options = {'DEFAULT_CLOSED'}
    use_pin = True

    @classmethod
    def poll(cls, context):
        try:
            return context.space_data.node_tree.bl_idname == 'SverchCustomTreeType'
        except:
            return False

    def draw(self, context):
        layout = self.layout
        layout.operator("node.sv_group_creator")
        
        for ng in bpy.data.node_groups:
            if ng.bl_idname == 'SverchGroupTreeType':
                layout.label(ng.name)
                op = layout.operator("node.sv_node_group_edit", text="Edit")
                op.group_name = ng.name
                
classes = [
    SverchokGroupLayoutsMenu,
    SvNodeGroupCreator,
    SvNodeGroupEdit,
    SvNodeGroupEditDone
]

def register():
    for class_name in classes:
        bpy.utils.register_class(class_name)

def unregister():
    for class_name in reversed(classes):
        bpy.utils.unregister_class(class_name)
