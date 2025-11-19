from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    aliases: Mapped[list["ManufacturerAlias"]] = relationship(
        "ManufacturerAlias", back_populates="manufacturer", cascade="all, delete-orphan"
    )
    parts: Mapped[list["Part"]] = relationship("Part", back_populates="manufacturer")


class ManufacturerAlias(Base):
    __tablename__ = "manufacturer_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturers.id", ondelete="CASCADE"))

    manufacturer: Mapped[Manufacturer] = relationship("Manufacturer", back_populates="aliases")


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(String(255), index=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    manufacturer_name: Mapped[str | None] = mapped_column(String(255))
    alias_used: Mapped[str | None] = mapped_column(String(255))
    submitted_manufacturer: Mapped[str | None] = mapped_column(String(255))
    match_status: Mapped[str | None] = mapped_column(String(50))
    match_confidence: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_url: Mapped[str | None] = mapped_column(Text)
    debug_log: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    manufacturer: Mapped[Manufacturer | None] = relationship("Manufacturer", back_populates="parts")
