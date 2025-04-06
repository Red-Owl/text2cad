-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: localhost:3307
-- Creato il: Apr 06, 2025 alle 12:21
-- Versione del server: 9.0.1
-- Versione PHP: 8.3.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `3d_objects`
--

-- --------------------------------------------------------

--
-- Struttura della tabella `aige_shapes`
--

CREATE TABLE `aige_shapes` (
  `shape_id` bigint UNSIGNED NOT NULL,
  `shape_name` varchar(50) NOT NULL,
  `shape_definition` json NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Definizioni delle forme 3D';

--
-- Dump dei dati per la tabella `aige_shapes`
--

INSERT INTO `aige_shapes` (`shape_id`, `shape_name`, `shape_definition`) VALUES
(1, 'box', '{\"type\": \"custom\", \"operations\": [{\"type\": \"cube\", \"width\": \"inner_width + 2 * wall_thickness\", \"center\": \"computed\", \"height\": \"inner_height + wall_thickness\", \"length\": \"inner_length + 2 * wall_thickness\", \"negative\": false}, {\"type\": \"cube\", \"width\": \"inner_width\", \"center\": \"computed\", \"height\": \"inner_height\", \"length\": \"inner_length\", \"negative\": true}, {\"type\": \"cube\", \"width\": \"inner_width + 2 * wall_thickness\", \"center\": \"computed\", \"height\": \"wall_thickness\", \"length\": \"inner_length + 2 * wall_thickness\", \"negative\": true}, {\"type\": \"cube\", \"width\": \"inner_width + 2 * inner_lip_width\", \"center\": \"computed\", \"height\": \"lid_thickness\", \"length\": \"inner_length + 2 * inner_lip_width\", \"negative\": false}, {\"type\": \"cylinder\", \"center\": \"computed\", \"height\": \"inner_height - 5\", \"radius\": \"screw_diameter + 2\", \"negative\": false}, {\"type\": \"cylinder\", \"center\": \"computed\", \"height\": \"inner_height - 5 + lid_thickness + 5\", \"radius\": \"screw_diameter / 2\", \"negative\": true}], \"parameters\": {\"inner_width\": 40, \"inner_height\": 50, \"inner_length\": 100, \"lid_thickness\": 1.6, \"screw_diameter\": 3, \"wall_thickness\": 1.6, \"inner_lip_width\": 0.8, \"inner_lip_height\": 0.8, \"screw_distance_from_edge\": 4}}');

--
-- Indici per le tabelle scaricate
--

--
-- Indici per le tabelle `aige_shapes`
--
ALTER TABLE `aige_shapes`
  ADD PRIMARY KEY (`shape_id`),
  ADD UNIQUE KEY `shape_name` (`shape_name`);

--
-- AUTO_INCREMENT per le tabelle scaricate
--

--
-- AUTO_INCREMENT per la tabella `aige_shapes`
--
ALTER TABLE `aige_shapes`
  MODIFY `shape_id` bigint UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
