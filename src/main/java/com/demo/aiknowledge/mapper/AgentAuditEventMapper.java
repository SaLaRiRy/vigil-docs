package com.demo.aiknowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.aiknowledge.entity.AgentAuditEvent;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface AgentAuditEventMapper extends BaseMapper<AgentAuditEvent> {
}
